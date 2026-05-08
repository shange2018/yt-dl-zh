#!/usr/bin/env python3
"""
yt_channel_list.py - 获取 YouTube 频道视频列表（Videos + Shorts）

用法:
  python3 yt_channel_list.py <频道名> [--limit 10] [--proxy http://127.0.0.1:2080] [--json] [--no-chinese]

数据获取流程:
  Step 1: yt-dlp --flat-playlist
          快速获取视频 ID + 英文标题（playlist 级别，不抓详情）
  Step 2: yt-dlp --dump-json（批量，每批 5 个）
          获取每个视频的完整详情:
            view_count, like_count, comment_count,
            upload_date, duration, filesize_approx
          注意: --dump-json --flat-playlist 不能合并用，
                合并时只有 id/title/duration 有值，互动数据为 None
  Step 3: 并发 curl YouTube 页面，正则提取中文标题
  Step 4: 合并排序，按发布日期倒序输出

输出字段:
  视频 ID、中文标题（优先）、发布日期、播放量、赞数、评论数、时长、文件大小
  （收藏数和分享数 YouTube 不公开，无法获取）
"""

import subprocess, json, os, re, sys, argparse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# ─── 配置 ────────────────────────────────────────────────────────────────────

DEFAULT_PROXY = "http://127.0.0.1:2080"
DEFAULT_LIMIT = 10
MAX_WORKERS = 5
REQUEST_TIMEOUT = 20

# ─── 工具函数 ────────────────────────────────────────────────────────────────

def run_yt_dlp(cmd, timeout=120):
    """运行 yt-dlp 命令"""
    env = {**os.environ, "https_proxy": args.proxy, "http_proxy": args.proxy}
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
    return r.stdout

def get_playlist_ids(channel_url, limit):
    """
    Step 1: --flat-playlist 快速获取 ID + 英文标题
    只解析 playlist，不抓每个视频详情，速度快
    """
    out = run_yt_dlp([
        "yt-dlp", "--flat-playlist",
        "--playlist-items", f"1-{limit}",
        "--print", "%(id)s\t%(title)s",
        channel_url,
    ], timeout=60)
    results = []
    for line in out.strip().split('\n'):
        if '\t' in line:
            parts = line.split('\t', 1)
            results.append({"id": parts[0], "title_en": parts[1] if len(parts) > 1 else ""})
    return results

def get_details_batch(video_ids):
    """
    Step 2: --dump-json 批量获取视频详情
    每批调用一次，返回:
      view_count, like_count, comment_count,
      upload_date, duration, filesize_approx
    """
    urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]
    out = run_yt_dlp(["yt-dlp", "--dump-json", "--no-download"] + urls, timeout=120)
    results = {}
    for line in out.strip().split('\n'):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            results[d['id']] = {
                'view_count': d.get('view_count'),
                'like_count': d.get('like_count'),
                'comment_count': d.get('comment_count'),
                'upload_date': d.get('upload_date'),       # 格式: 20260502
                'duration': d.get('duration'),             # 秒
                'filesize_approx': d.get('filesize_approx'),  # bytes
            }
        except json.JSONDecodeError:
            pass
    return results

def get_chinese_title(video_id):
    """Step 3: 从 YouTube 页面 HTML 提取中文标题"""
    try:
        proxy_handler = urllib.request.ProxyHandler({
            'http': args.proxy, 'https': args.proxy,
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

        # title.runs[0].text — 最常见的中文标题位置
        m = re.search(r'"title":\{"runs":\[\{"text":"([^"]+)"', html)
        if m:
            return m.group(1)

        # Shorts 特有的 shortsVideoTitleViewModel
        m = re.search(r'"shortsVideoTitleViewModel":\{[^}]*"content":"([^"]+)"', html)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None

def fmt_num(n):
    """1234567 → 123.5万"""
    if n is None:
        return "N/A"
    if n >= 10000:
        return f"{n/10000:.1f}万"
    return f"{n:,}"

def fmt_date(d):
    """20260502 → 2026-05-02"""
    if not d or len(d) != 8:
        return str(d)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

def fmt_dur(s):
    """7265 → 2:01:05 / 45 → 0:45"""
    if s is None:
        return "N/A"
    s = int(s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

def fmt_size(b):
    """bytes → 自动换算 MB/GB"""
    if b is None:
        return "N/A"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

# ─── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    global args
    parser = argparse.ArgumentParser(description="获取 YouTube 频道视频列表")
    parser.add_argument("channel", help="频道名（不含 @），如 StokesTwins")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--proxy", default=DEFAULT_PROXY)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--no-chinese", action="store_true", help="跳过中文标题（更快）")
    args = parser.parse_args()

    base = f"https://www.youtube.com/@{args.channel}"

    # ── Step 1: 获取视频 ID + 英文标题 ───────────────────────────────────
    print(f"📡 [1/4] 获取 Videos 列表（前 {args.limit} 个）...", file=sys.stderr)
    videos = get_playlist_ids(f"{base}/videos", args.limit)
    print(f"  → {len(videos)} 个 Videos", file=sys.stderr)

    print(f"📡 [2/4] 获取 Shorts 列表（前 {args.limit} 个）...", file=sys.stderr)
    shorts = get_playlist_ids(f"{base}/shorts", args.limit)
    print(f"  → {len(shorts)} 个 Shorts", file=sys.stderr)

    # 合并去重
    seen = set()
    all_vids = []
    for v in videos + shorts:
        if v['id'] not in seen:
            seen.add(v['id'])
            v['is_short'] = v in shorts and v not in videos
            all_vids.append(v)

    total = len(all_vids)
    if total == 0:
        print("❌ 未获取到视频", file=sys.stderr)
        sys.exit(1)
    print(f"  → 共 {total} 个视频（去重后）", file=sys.stderr)

    # ── Step 2: 批量获取视频详情 ─────────────────────────────────────────
    all_ids = [v['id'] for v in all_vids]
    details = {}
    batch_size = 5

    print(f"📡 [3/4] 获取视频详情（{total} 个，每批 {batch_size} 个）...", file=sys.stderr)
    for i in range(0, total, batch_size):
        batch = all_ids[i:i+batch_size]
        bn = i // batch_size + 1
        bt = (total + batch_size - 1) // batch_size
        print(f"  批次 {bn}/{bt}...", file=sys.stderr)
        try:
            data = get_details_batch(batch)
            details.update(data)
        except subprocess.TimeoutExpired:
            print(f"  ⚠️ 批次 {bn} 超时，跳过", file=sys.stderr)

    # ── Step 3: 获取中文标题 ─────────────────────────────────────────────
    zh_map = {}
    if not args.no_chinese:
        print(f"📡 [4/4] 获取中文标题（{total} 个，并发 {MAX_WORKERS}）...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(get_chinese_title, v['id']): v['id'] for v in all_vids}
            done = 0
            for f in as_completed(futs):
                done += 1
                vid = futs[f]
                try:
                    zh = f.result()
                    zh_map[vid] = zh
                    icon = "✓" if zh else "✗"
                    print(f"  {icon} [{done}/{total}] {zh or vid}", file=sys.stderr)
                except Exception as e:
                    print(f"  ✗ [{done}/{total}] {vid}: {e}", file=sys.stderr)
    else:
        print("⏭️  跳过中文标题", file=sys.stderr)

    # ── Step 4: 排序输出 ─────────────────────────────────────────────────
    all_vids.sort(key=lambda v: (details.get(v['id']) or {}).get('upload_date') or '', reverse=True)

    rows = []
    for v in all_vids:
        d = details.get(v['id'], {})
        zh = zh_map.get(v['id'], '')
        title = zh if zh else v['title_en']
        rows.append({
            "id": v['id'],
            "title": title,
            "date": fmt_date(d.get('upload_date')),
            "views": d.get('view_count'),
            "likes": d.get('like_count'),
            "comments": d.get('comment_count'),
            "duration": d.get('duration'),
            "size": d.get('filesize_approx'),
            "is_short": v.get('is_short', False),
            "url": f"https://www.youtube.com/watch?v={v['id']}",
        })

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        header = f"{'ID':<12} {'发布日期':<12} {'播放量':>10} {'赞数':>10} {'评论数':>8} {'时长':>8} {'大小':>10} {'标题'}"
        sep = "─" * 130
        print(f"\n{sep}\n{header}\n{sep}")
        for r in rows:
            tag = " [Short]" if r['is_short'] else ""
            print(f"{r['id']:<12} {r['date']:<12} {fmt_num(r['views']):>10} {fmt_num(r['likes']):>10} "
                  f"{fmt_num(r['comments']):>8} {fmt_dur(r['duration']):>8} {fmt_size(r['size']):>10} "
                  f"{r['title']}{tag}")
        print(sep)
        vc = sum(1 for r in rows if not r['is_short'])
        sc = sum(1 for r in rows if r['is_short'])
        print(f"总计: {len(rows)} 个（Videos: {vc}, Shorts: {sc}）")
        print("注: 收藏数和分享数 YouTube 不公开，无法获取")

if __name__ == "__main__":
    main()
