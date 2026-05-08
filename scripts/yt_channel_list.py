#!/usr/bin/env python3
"""
yt_channel_list.py - 获取 YouTube 频道视频列表（Videos + Shorts）

用法:
  python3 yt_channel_list.py <频道名> [--limit 10] [--proxy http://127.0.0.1:2080] [--json]

输出字段:
  中文标题、英文标题、发布日期、播放量、赞数、评论数、视频ID、时长、文件大小
  （收藏数和分享数 YouTube 不公开，无法获取）

示例:
  python3 yt_channel_list.py StokesTwins --limit 10
  python3 yt_channel_list.py StokesTwins --limit 20 --json > list.json
"""

import subprocess, json, os, re, sys, argparse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ─── 配置 ────────────────────────────────────────────────────────────────────

DEFAULT_PROXY = "http://127.0.0.1:2080"
DEFAULT_LIMIT = 10
MAX_WORKERS = 5  # 并发获取中文标题的线程数
REQUEST_TIMEOUT = 20  # 单个请求超时（秒）

# ─── 工具函数 ────────────────────────────────────────────────────────────────

def run_cmd(cmd, timeout=60):
    """运行命令并返回 stdout"""
    env = {**os.environ, "https_proxy": args.proxy, "http_proxy": args.proxy}
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    return r.stdout

def get_video_ids_and_titles(channel_url, limit):
    """用 yt-dlp --flat-playlist 获取视频 ID 和英文标题"""
    out = run_cmd([
        "yt-dlp", "--flat-playlist",
        "--playlist-items", f"1-{limit}",
        "--print", "%(id)s\t%(title)s",
        channel_url
    ], timeout=60)
    results = []
    for line in out.strip().split('\n'):
        if '\t' in line:
            parts = line.split('\t', 1)
            results.append({"id": parts[0], "title_en": parts[1] if len(parts) > 1 else ""})
    return results

def get_engagement_data(video_ids):
    """用 yt-dlp --dump-json 批量获取互动数据"""
    urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]
    out = run_cmd(["yt-dlp", "--dump-json", "--no-download"] + urls, timeout=120)
    results = {}
    for line in out.strip().split('\n'):
        if line.strip():
            try:
                d = json.loads(line)
                results[d['id']] = {
                    'view_count': d.get('view_count'),
                    'like_count': d.get('like_count'),
                    'comment_count': d.get('comment_count'),
                    'upload_date': d.get('upload_date'),
                    'duration': d.get('duration'),           # 时长（秒）
                    'filesize_approx': d.get('filesize_approx'),  # 文件大小（bytes）
                }
            except json.JSONDecodeError:
                pass
    return results

def get_chinese_title(video_id):
    """从 YouTube 页面提取中文标题"""
    try:
        import urllib.request
        proxy_handler = urllib.request.ProxyHandler({
            'http': args.proxy,
            'https': args.proxy,
        })
        opener = urllib.request.build_opener(proxy_handler)
        req = urllib.request.Request(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }
        )
        resp = opener.open(req, timeout=REQUEST_TIMEOUT)
        html = resp.read().decode('utf-8', errors='replace')

        # 方法1: title.runs[0].text（最常见）
        m = re.search(r'"title":\{"runs":\[\{"text":"([^"]+)"', html)
        if m:
            return m.group(1)

        # 方法2: shortsVideoTitleViewModel
        m = re.search(r'"shortsVideoTitleViewModel":\{[^}]*"content":"([^"]+)"', html)
        if m:
            return m.group(1)

    except Exception:
        pass
    return None

def format_number(n):
    """格式化数字，如 1234567 → 123.5万 / 1,234,567"""
    if n is None:
        return "N/A"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return f"{n:,}"

def format_date(d):
    """20260502 → 2026-05-02"""
    if not d or len(d) != 8:
        return str(d)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

def format_duration(seconds):
    """7265 → 2:01:05  /  45 → 0:45"""
    if seconds is None:
        return "N/A"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

def format_size(bytes_):
    """123456789 → 117.7 MB"""
    if bytes_ is None:
        return "N/A"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if abs(bytes_) < 1024:
            return f"{bytes_:.1f} {unit}"
        bytes_ /= 1024
    return f"{bytes_:.1f} TB"

# ─── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    global args
    parser = argparse.ArgumentParser(description="获取 YouTube 频道视频列表")
    parser.add_argument("channel", help="频道名（不含 @），如 StokesTwins")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"每种类型获取数量（默认 {DEFAULT_LIMIT}）")
    parser.add_argument("--proxy", default=DEFAULT_PROXY, help=f"代理地址（默认 {DEFAULT_PROXY}）")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--no-chinese", action="store_true", help="跳过中文标题获取（更快）")
    args = parser.parse_args()

    channel = args.channel
    limit = args.limit
    base = f"https://www.youtube.com/@{channel}"

    # ── Step 1: 获取视频 ID 列表 ────────────────────────────────────────
    print(f"📡 [1/3] 获取 Videos（前 {limit} 个）...", file=sys.stderr)
    try:
        videos = get_video_ids_and_titles(f"{base}/videos", limit)
    except subprocess.TimeoutExpired:
        videos = []
    print(f"  → {len(videos)} 个 Videos", file=sys.stderr)

    print(f"📡 [2/3] 获取 Shorts（前 {limit} 个）...", file=sys.stderr)
    try:
        shorts = get_video_ids_and_titles(f"{base}/shorts", limit)
    except subprocess.TimeoutExpired:
        shorts = []
    print(f"  → {len(shorts)} 个 Shorts", file=sys.stderr)

    # 合并（去重）
    seen = set()
    all_videos = []
    for v in videos + shorts:
        if v['id'] not in seen:
            seen.add(v['id'])
            v['type'] = 'short' if v in shorts and v not in videos else 'video'
            all_videos.append(v)

    total = len(all_videos)
    if total == 0:
        print("❌ 未获取到视频列表", file=sys.stderr)
        sys.exit(1)

    print(f"  → 共 {total} 个视频（去重后）", file=sys.stderr)

    # ── Step 2: 获取互动数据 ────────────────────────────────────────────
    all_ids = [v['id'] for v in all_videos]
    engagement = {}

    print(f"📡 [3/3] 获取互动数据（{len(all_ids)} 个视频）...", file=sys.stderr)
    for i in range(0, len(all_ids), 5):
        batch = all_ids[i:i+5]
        batch_num = i // 5 + 1
        total_batches = (len(all_ids) + 4) // 5
        print(f"  批次 {batch_num}/{total_batches}...", file=sys.stderr)
        try:
            data = get_engagement_data(batch)
            engagement.update(data)
        except subprocess.TimeoutExpired:
            print(f"  ⚠️ 批次 {batch_num} 超时，跳过", file=sys.stderr)

    # ── Step 3: 获取中文标题 ────────────────────────────────────────────
    zh_titles = {}
    if not args.no_chinese:
        print(f"📡 获取中文标题（{len(all_ids)} 个，并发 {MAX_WORKERS} 线程）...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = {ex.submit(get_chinese_title, vid): vid for vid in all_ids}
            done = 0
            for future in as_completed(futures):
                done += 1
                vid = futures[future]
                try:
                    result = future.result()
                    zh_titles[vid] = result
                    if result:
                        print(f"  ✓ [{done}/{len(all_ids)}] {result}", file=sys.stderr)
                    else:
                        print(f"  ✗ [{done}/{len(all_ids)}] {vid}: 无中文标题", file=sys.stderr)
                except Exception as e:
                    print(f"  ✗ [{done}/{len(all_ids)}] {vid}: {e}", file=sys.stderr)
    else:
        print("⏭️  跳过中文标题获取", file=sys.stderr)

    # ── 按发布日期排序 ──────────────────────────────────────────────────
    def sort_key(v):
        eng = engagement.get(v['id'], {})
        return eng.get('upload_date', '') or ''

    all_videos.sort(key=sort_key, reverse=True)

    # ── 输出 ────────────────────────────────────────────────────────────
    output_data = []
    for v in all_videos:
        vid = v['id']
        eng = engagement.get(vid, {})
        upload_date = eng.get('upload_date', '')
        zh = zh_titles.get(vid, '')
        title_display = zh if zh else v['title_en']

        row = {
            "id": vid,
            "title_zh": zh,
            "title_en": v['title_en'],
            "title": title_display,
            "date": format_date(upload_date),
            "views": eng.get('view_count'),
            "likes": eng.get('like_count'),
            "comments": eng.get('comment_count'),
            "duration": eng.get('duration'),
            "filesize": eng.get('filesize_approx'),
            "type": v['type'],
            "url": f"https://www.youtube.com/watch?v={vid}",
        }
        output_data.append(row)

    if args.json:
        # JSON 输出
        print(json.dumps(output_data, ensure_ascii=False, indent=2))
    else:
        # 表格输出
        # 表头
        header = f"{'ID':<12} {'发布日期':<12} {'播放量':>10} {'赞数':>10} {'评论数':>8} {'时长':>8} {'大小':>10} {'标题'}"
        sep = "─" * 130
        print(f"\n{sep}")
        print(header)
        print(sep)

        for row in output_data:
            views_s = format_number(row['views'])
            likes_s = format_number(row['likes'])
            comm_s = format_number(row['comments'])
            dur_s = format_duration(row['duration'])
            size_s = format_size(row['filesize'])
            type_tag = " [Short]" if row['type'] == 'short' else ""
            print(f"{row['id']:<12} {row['date']:<12} {views_s:>10} {likes_s:>10} {comm_s:>8} {dur_s:>8} {size_s:>10} {row['title']}{type_tag}")

        print(sep)
        videos_count = sum(1 for r in output_data if r['type'] == 'video')
        shorts_count = sum(1 for r in output_data if r['type'] == 'short')
        print(f"总计: {len(output_data)} 个（Videos: {videos_count}, Shorts: {shorts_count}）")
        print(f"注: 收藏数和分享数 YouTube 不公开，无法获取")

if __name__ == "__main__":
    main()
