#!/usr/bin/env python3
"""
yt_monitor.py - YouTube 监控下载

流程:
  1. 从 youtuber_list.md 读取频道列表
  2. 对每个频道，抓取 /videos 页面获取最新视频列表
  3. 过滤: 发布日期 >= 20260101，标题含中文字符
  4. 对比 videos/shorts 表，跳过已存在的记录
  5. 插入新记录到数据库
  6. 用 yt-dlp 下载视频(MP4) + 中文音轨，合并，以中文标题命名

依赖:
  yt-dlp (with yt-dlp-ejs), node v24, ffmpeg

用法:
  python3 yt_monitor.py                          # 处理所有频道
  python3 yt_monitor.py --channel StokesTwins    # 只处理指定频道
  python3 yt_monitor.py --dry-run                # 只扫描不下载
  python3 yt_monitor.py --list                   # 只输出视频列表
"""

import re, json, os, sys, sqlite3, subprocess, argparse, urllib.request
from datetime import datetime, timedelta

# ─── 配置 ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROXY     = "http://127.0.0.1:2080"
UA        = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
MIN_DATE  = "20260101"  # 只保留此日期之后的视频
DOWNLOAD_DIR = os.path.expanduser("~/youtube-downloads")

# ─── 数据库 ──────────────────────────────────────────────────────────────────

def open_db(youtuber):
    """打开（或创建）某频道的 SQLite 数据库"""
    db_path = os.path.join(SCRIPT_DIR, "videos_shorts_list.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        yountuber TEXT NOT NULL,
        video_id TEXT UNIQUE NOT NULL,
        title TEXT,
        duration TEXT,
        views TEXT,
        pub_date TEXT,
        downloaded INTEGER DEFAULT 1,
        file_path TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS shorts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        yountuber TEXT NOT NULL,
        short_id TEXT UNIQUE NOT NULL,
        title TEXT,
        duration TEXT,
        views TEXT,
        pub_date TEXT,
        downloaded INTEGER DEFAULT 1,
        file_path TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()
    return conn

def exists_in_db(conn, table, id_col, vid):
    """检查视频是否已下载成功（downloaded=0）"""
    c = conn.cursor()
    c.execute(f"SELECT 1 FROM {table} WHERE {id_col} = ? AND downloaded = 0", (vid,))
    return c.fetchone() is not None

def insert_video(conn, table, id_col, data):
    """插入一条视频记录"""
    c = conn.cursor()
    vid = data.get('video_id') or data.get('short_id')
    c.execute(f"""INSERT OR IGNORE INTO {table}
                  (youtuber, {id_col}, title, duration, views, pub_date)
                  VALUES (?, ?, ?, ?, ?, ?)""",
              (data['youtuber'], vid, data['title'],
               data.get('duration', ''), data.get('views', ''),
               data.get('pub_date', '')))
    conn.commit()
    return c.rowcount > 0

# ─── 页面抓取 ────────────────────────────────────────────────────────────────

def fetch_page(url, proxy=PROXY):
    proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    resp = opener.open(req, timeout=30)
    return resp.read().decode('utf-8', errors='replace')

def extract_yt_initial_data(html):
    m = re.search(r'var ytInitialData = ({.*?});', html, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError("未找到 ytInitialData")

def parse_relative_date(text):
    """将 '5天前' 转换为 '2026-05-03' 格式"""
    if not text:
        return None
    now = datetime.now()
    text = text.strip()
    m = re.match(r'(\d+)\s*小时前', text)
    if m:
        dt = now - timedelta(hours=int(m.group(1)))
    else:
        m = re.match(r'(\d+)\s*天前', text)
        if m:
            dt = now - timedelta(days=int(m.group(1)))
        else:
            m = re.match(r'(\d+)\s*周前', text)
            if m:
                dt = now - timedelta(weeks=int(m.group(1)))
            else:
                m = re.match(r'(\d+)\s*个月前', text)
                if m:
                    dt = now - timedelta(days=int(m.group(1)) * 30)
                else:
                    m = re.match(r'(\d+)\s*年前', text)
                    if m:
                        dt = now - timedelta(days=int(m.group(1)) * 365)
                    else:
                        return None
    return dt.strftime("%Y%m%d")

def has_chinese(text):
    """检查文本中是否含有中文字符"""
    if not text:
        return False
    return bool(re.search(r'[\u4e00-\u9fff]', text))

def parse_video_item(item):
    """从 richItemRenderer 解析单个视频数据"""
    lvm = item.get('richItemRenderer', {}).get('content', {}).get('lockupViewModel', {})
    if not lvm:
        return None

    vid = lvm.get('contentId', '')
    if not vid:
        return None

    content_type = lvm.get('contentType', '')
    is_short = content_type == 'LOCKUP_CONTENT_TYPE_SHORTS'

    md_vm = lvm.get('metadata', {}).get('lockupMetadataViewModel', {})
    title = md_vm.get('title', {}).get('content', '')

    rows = (md_vm.get('metadata', {})
                .get('contentMetadataViewModel', {})
                .get('metadataRows', []))
    views = ''
    pub_time_raw = ''
    if rows:
        parts = rows[0].get('metadataParts', [])
        if len(parts) >= 1:
            views = parts[0].get('text', {}).get('content', '')
        if len(parts) >= 2:
            pub_time_raw = parts[1].get('text', {}).get('content', '')

    pub_date = parse_relative_date(pub_time_raw)

    duration = ''
    overlays = (lvm.get('contentImage', {})
                    .get('thumbnailViewModel', {})
                    .get('overlays', []))
    if overlays:
        badges = (overlays[0].get('thumbnailBottomOverlayViewModel', {})
                            .get('badges', []))
        if badges:
            duration = badges[0].get('thumbnailBadgeViewModel', {}).get('text', '')

    return {
        'video_id': vid,
        'title': title,
        'views': views,
        'pub_date': pub_date,
        'pub_time_raw': pub_time_raw,
        'duration': duration,
        'is_short': is_short,
    }

def scrape_channel(channel):
    """抓取频道 /videos 页面，返回过滤后的视频列表"""
    url = f"https://www.youtube.com/@{channel}/videos"
    html = fetch_page(url)
    data = extract_yt_initial_data(html)

    try:
        contents = (data['contents']['twoColumnBrowseResultsRenderer']
                          ['tabs'][1]['tabRenderer']['content']
                          ['richGridRenderer']['contents'])
    except (KeyError, IndexError):
        return []

    videos = []
    shorts = []
    for item in contents:
        if 'richItemRenderer' not in item:
            continue
        v = parse_video_item(item)
        if not v:
            continue

        # 过滤1: 发布日期 >= 20260101
        if v['pub_date'] and v['pub_date'] < MIN_DATE:
            print(f"  ⏭️  跳过(日期太早 {v['pub_date']}): {v['title'][:40]}", file=sys.stderr)
            continue

        # 过滤2: 标题含中文
        if not has_chinese(v['title']):
            print(f"  ⏭️  跳过(无中文标题): {v['title'][:40]}", file=sys.stderr)
            continue

        v['youtuber'] = channel
        if v['is_short']:
            shorts.append(v)
        else:
            videos.append(v)

    return videos, shorts

# ─── 下载 ────────────────────────────────────────────────────────────────────

def sanitize_filename(title):
    """清理文件名中的非法字符"""
    title = re.sub(r'[/\\:*?"<>|]', '', title)
    title = title.strip()
    if len(title) > 200:
        title = title[:200]
    return title

def download_video(video_id, title, proxy=PROXY):
    """
    用 yt-dlp 下载视频(MP4) + 中文音轨，合并输出
    输出文件: ~/youtube-downloads/<中文标题>.mp4
    """
    out_dir = DOWNLOAD_DIR
    os.makedirs(out_dir, exist_ok=True)

    safe_title = sanitize_filename(title)
    out_path = os.path.join(out_dir, f"{safe_title}.mp4")

    # 如果文件已存在则跳过
    if os.path.exists(out_path):
        print(f"  ✅ 文件已存在，跳过: {safe_title}.mp4", file=sys.stderr)
        return out_path

    env = {
        **os.environ,
        "https_proxy": proxy,
        "http_proxy": proxy,
    }

    cmd = [
        "yt-dlp",
        "--proxy", proxy,
        "--extractor-args", "youtube:player_client=web_embedded",
        "--js-runtimes", "node",
        "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "-o", os.path.join(out_dir, "%(title)s.%(ext)s"),
        "--no-overwrites",
        "--newline",
        f"https://www.youtube.com/watch?v={video_id}",
    ]

    print(f"  ⬇️  下载中: {title[:50]}...", file=sys.stderr)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
        if r.returncode != 0:
            print(f"  ❌ 下载失败:\n{r.stderr[-500:]}", file=sys.stderr)
            return None
        print(f"  ✅ 下载完成: {safe_title}.mp4", file=sys.stderr)
        return out_path
    except subprocess.TimeoutExpired:
        print(f"  ❌ 下载超时: {title[:50]}", file=sys.stderr)
        return None

# ─── 主流程 ──────────────────────────────────────────────────────────────────

def load_youtuber_list(path):
    """从 youtuber_list.md 读取活跃频道列表（只取合法的 YouTube 频道名）"""
    channels = []
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 去掉列表标记
            if line.startswith('- '):
                line = line[2:].strip()
            # YouTube 频道名只含英文、数字、下划线、连字符
            if re.match(r'^[A-Za-z0-9_-]+$', line):
                channels.append(line)
    return channels

def main():
    parser = argparse.ArgumentParser(description="YouTube 监控下载")
    parser.add_argument("--channel", help="只处理指定频道")
    parser.add_argument("--dry-run", action="store_true", help="只扫描，不下载")
    parser.add_argument("--list", action="store_true", help="只输出视频列表")
    parser.add_argument("--limit", type=int, default=50, help="每次抓取视频数")
    parser.add_argument("--proxy", default=PROXY)
    args = parser.parse_args()

    # 读取频道列表
    list_path = os.path.join(SCRIPT_DIR, "youtuber_list.md")
    if args.channel:
        channels = [args.channel]
    elif os.path.exists(list_path):
        channels = load_youtuber_list(list_path)
    else:
        print(f"❌ 未找到 {list_path}，请创建或指定 --channel", file=sys.stderr)
        sys.exit(1)

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    total_new = 0
    total_dl  = 0

    for channel in channels:
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"📡 处理 @{channel}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        conn = open_db(channel)

        # 抓取视频列表
        print(f"  🔍 抓取 @{channel}/videos ...", file=sys.stderr)
        try:
            videos, shorts = scrape_channel(channel)
        except Exception as e:
            print(f"  ❌ 抓取失败: {e}", file=sys.stderr)
            conn.close()
            continue

        print(f"  📋 Videos: {len(videos)} 个, Shorts: {len(shorts)} 个", file=sys.stderr)

        # 合并处理
        all_items = [('videos', 'video_id', v) for v in videos] + \
                    [('shorts', 'short_id', s) for s in shorts]

        new_items = []
        for table, id_col, item in all_items:
            if exists_in_db(conn, table, id_col, item['video_id']):
                print(f"  ⏭️  已存在: {item['title'][:40]}", file=sys.stderr)
                continue
            insert_video(conn, table, id_col, item)
            new_items.append((table, id_col, item))
            print(f"  🆕 新增: {item['title'][:50]} ({item['pub_date']})", file=sys.stderr)

        total_new += len(new_items)

        # 只输出列表模式
        if args.list:
            print(f"\n{'─'*80}")
            print(f"{'类型':>6}  {'ID':<12} {'日期':<12} {'标题'}")
            print(f"{'─'*80}")
            for table, id_col, item in new_items:
                print(f"{table:>6}  {item['video_id']:<12} {item['pub_date'] or 'N/A':<12} {item['title']}")
            conn.close()
            continue

        # 下载新视频（已注释，改为输出待下载列表）
        # if not args.dry_run:
        #     for table, id_col, item in new_items:
        #         result = download_video(item['video_id'], item['title'], args.proxy)
        #         if result:
        #             c = conn.cursor()
        #             c.execute(f"UPDATE {table} SET downloaded=0, file_path=? WHERE {id_col}=?",
        #                       (result, item['video_id']))
        #             conn.commit()
        #             total_dl += 1
        #             print(f"  ✅ 下载完成: {item['title'][:40]}", file=sys.stderr)
        #         else:
        #             c = conn.cursor()
        #             c.execute(f"UPDATE {table} SET downloaded = downloaded + 1 WHERE {id_col}=?",
        #                       (item['video_id'],))
        #             conn.commit()
        #             print(f"  ❌ 下载失败 (第N次): {item['title'][:40]}", file=sys.stderr)
        # else:
        #     print(f"  🔍 dry-run 模式，已插入 {len(new_items)} 条 (downloaded=1)", file=sys.stderr)

        # 输出待下载列表
        if new_items:
            print(f"\n{'='*60}", file=sys.stderr)
            print(f"📋 待下载列表 ({len(new_items)} 个):", file=sys.stderr)
            print(f"{'='*60}", file=sys.stderr)
            for i, (table, id_col, item) in enumerate(new_items, 1):
                print(f"  {i:>3}. [{table}] {item['video_id']}  {item['pub_date'] or 'N/A'}  {item['title']}", file=sys.stderr)
        else:
            print(f"  ✅ 没有新视频需要下载", file=sys.stderr)

        conn.close()

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"📊 扫描完成: 新增 {total_new} 个视频", file=sys.stderr)
    # if not args.dry_run:
    #     print(f"📊 下载完成: {total_dl} 个视频 → {DOWNLOAD_DIR}", file=sys.stderr)

if __name__ == "__main__":
    main()
