#!/usr/bin/env python3
"""
yt_channel_scraper.py - 直接从 YouTube 页面抓取频道视频列表

原理:
  请求 https://www.youtube.com/@<频道名>/videos 页面
  从 ytInitialData JSON 中提取视频数据

  页面结构 (YouTube 2024+ 新 UI):
    ytInitialData
      .contents.twoColumnBrowseResultsRenderer
        .tabs[1].tabRenderer.content.richGridRenderer.contents[]
          .richItemRenderer.content.lockupViewModel
            .contentId                    → 视频 ID
            .contentType                 → LOCKUP_CONTENT_TYPE_VIDEO / SHORTS
            .metadata.lockupMetadataViewModel
              .title.content             → 中文标题
              .metadata.contentMetadataViewModel.metadataRows[0]
                .metadataParts[0].text.content  → 播放量 (如 "1150万")
                .metadataParts[1].text.content  → 发布时间 (如 "5天前")
            .contentImage.thumbnailViewModel.overlays[0]
              .thumbnailBottomOverlayViewModel.badges[0]
                .thumbnailBadgeViewModel.text  → 时长 (如 "58:33")

  注意: 页面只显示约 30 个视频，需要翻页获取更多

用法:
  python3 yt_channel_scraper.py <频道名> [--limit 30] [--proxy http://127.0.0.1:2080] [--json]
"""

import re, json, sys, argparse, urllib.request
from urllib.error import URLError
from datetime import datetime, timedelta

# ─── 配置 ────────────────────────────────────────────────────────────────────

DEFAULT_PROXY = "http://127.0.0.1:2080"
DEFAULT_LIMIT = 30
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# ─── 网络请求 ────────────────────────────────────────────────────────────────

def fetch_page(url, proxy):
    """请求 YouTube 页面，返回 HTML"""
    proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    resp = opener.open(req, timeout=30)
    return resp.read().decode('utf-8', errors='replace')

def extract_yt_initial_data(html):
    """从 HTML 中提取 ytInitialData JSON"""
    m = re.search(r'var ytInitialData = ({.*?});', html, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    m = re.search(r'window\["ytInitialData"\] = ({.*?});', html, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    raise ValueError("未找到 ytInitialData")

# ─── 数据解析 ────────────────────────────────────────────────────────────────

def parse_video_item(item):
    """从单个 richItemRenderer 解析视频数据"""
    lvm = item.get('richItemRenderer', {}).get('content', {}).get('lockupViewModel', {})
    if not lvm:
        return None

    vid = lvm.get('contentId', '')
    if not vid:
        return None

    content_type = lvm.get('contentType', '')
    is_short = content_type == 'LOCKUP_CONTENT_TYPE_SHORTS'

    # 标题
    md_vm = lvm.get('metadata', {}).get('lockupMetadataViewModel', {})
    title = md_vm.get('title', {}).get('content', '')

    # 播放量 + 发布时间
    views = ''
    pub_time = ''
    rows = (md_vm.get('metadata', {})
                .get('contentMetadataViewModel', {})
                .get('metadataRows', []))
    if rows:
        parts = rows[0].get('metadataParts', [])
        if len(parts) >= 1:
            views = parts[0].get('text', {}).get('content', '')
        if len(parts) >= 2:
            pub_time = parts[1].get('text', {}).get('content', '')

    # 时长
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
        'id': vid,
        'title': title,
        'views': views,
        'pub_time': pub_time,
        'duration': duration,
        'is_short': is_short,
        'url': f'https://www.youtube.com/watch?v={vid}',
    }

def get_continuation_token(data):
    """获取翻页 token（用于加载更多视频）"""
    try:
        contents = (data['contents']['twoColumnBrowseResultsRenderer']
                          ['tabs'][1]['tabRenderer']['content']
                          ['richGridRenderer']['contents'])
        # 最后一项可能是 continuationItemRenderer
        last = contents[-1]
        if 'continuationItemRenderer' in last:
            return (last['continuationItemRenderer']
                        ['continuationEndpoint']
                        ['continuationCommand']['token'])
    except (KeyError, IndexError):
        pass
    return None

def fetch_more_videos(token, proxy):
    """用 continuation token 获取更多视频"""
    url = "https://www.youtube.com/youtubei/v1/browse"
    data = json.dumps({
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20241201.00.00",
                "hl": "zh-CN",
            }
        },
        "continuation": token,
    }).encode()

    proxy_handler = urllib.request.ProxyHandler({'http': proxy, 'https': proxy})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    resp = opener.open(req, timeout=30)
    return json.loads(resp.read().decode('utf-8', errors='replace'))

def parse_continuation_data(data):
    """解析 continuation 响应中的视频"""
    results = []
    try:
        items = (data['onResponseReceivedActions'][0]
                      ['appendContinuationItemsAction']
                      ['continuationItems'])
        for item in items:
            if 'richItemRenderer' in item:
                v = parse_video_item(item)
                if v:
                    results.append(v)
    except (KeyError, IndexError):
        pass
    return results

# ─── 格式化 ──────────────────────────────────────────────────────────────────

def fmt_dur(s):
    """58:33 → 58:33 / 1:04:14 → 1:04:14"""
    return s or "N/A"

def fmt_num(s):
    """1150万 → 1150万 / 1.6亿 → 1.6亿"""
    return s or "N/A"

def parse_relative_date(text):
    """
    将 YouTube 相对发布时间转换为绝对日期。
    支持格式: 5天前, 2小时前, 3周前, 2个月前, 1年前
    返回: (原始文本, 计算出的日期字符串 YYYY-MM-DD)
    """
    if not text:
        return text, "N/A"

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
                        return text, text

    return text, dt.strftime("%Y-%m-%d")

# ─── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    global args
    parser = argparse.ArgumentParser(description="从 YouTube 页面抓取频道视频列表")
    parser.add_argument("channel", help="频道名（不含 @），如 StokesTwins")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"获取视频数（默认 {DEFAULT_LIMIT}，页面一次约 30 个）")
    parser.add_argument("--proxy", default=DEFAULT_PROXY)
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    base = f"https://www.youtube.com/@{args.channel}"

    # ── Step 1: 获取首页面 ────────────────────────────────────────────────
    print(f"📡 [1/2] 获取 @{args.channel}/videos 页面...", file=sys.stderr)
    try:
        html = fetch_page(f"{base}/videos", args.proxy)
    except Exception as e:
        print(f"❌ 请求失败: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        data = extract_yt_initial_data(html)
    except ValueError as e:
        print(f"❌ 解析失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 解析视频列表
    try:
        contents = (data['contents']['twoColumnBrowseResultsRenderer']
                          ['tabs'][1]['tabRenderer']['content']
                          ['richGridRenderer']['contents'])
    except (KeyError, IndexError):
        print("❌ 未找到视频列表", file=sys.stderr)
        sys.exit(1)

    videos = []
    for item in contents:
        if 'richItemRenderer' in item:
            v = parse_video_item(item)
            if v:
                videos.append(v)

    print(f"  → 首页面获取 {len(videos)} 个视频", file=sys.stderr)

    # ── Step 2: 翻页获取更多 ─────────────────────────────────────────────
    fetched = len(videos)
    page = 2
    while fetched < args.limit:
        token = get_continuation_token(data)
        if not token:
            print(f"  → 无更多翻页 token，停止", file=sys.stderr)
            break

        print(f"📡 [{page}/2+] 翻页获取更多视频...", file=sys.stderr)
        try:
            more_data = fetch_more_videos(token, args.proxy)
            new_videos = parse_continuation_data(more_data)
            if not new_videos:
                break
            videos.extend(new_videos)
            fetched = len(videos)
            print(f"  → 累计 {fetched} 个视频", file=sys.stderr)
            # 更新 data 用于下次翻页
            data = more_data
            page += 1
        except Exception as e:
            print(f"  ⚠️ 翻页失败: {e}", file=sys.stderr)
            break

    # 截取需要的数量
    videos = videos[:args.limit]

    # 转换相对日期为绝对日期
    for v in videos:
        _, v['date'] = parse_relative_date(v['pub_time'])

    # ── 输出 ──────────────────────────────────────────────────────────────
    if args.json:
        print(json.dumps(videos, ensure_ascii=False, indent=2))
    else:
        header = f"{'ID':<12} {'时长':>8} {'播放量':>10} {'发布日期':>12} {'标题'}"
        sep = "─" * 110
        print(f"\n{sep}\n{header}\n{sep}")
        for v in videos:
            orig_date, abs_date = parse_relative_date(v['pub_time'])
            tag = " [Short]" if v['is_short'] else ""
            print(f"{v['id']:<12} {fmt_dur(v['duration']):>8} {fmt_num(v['views']):>10} "
                  f"{abs_date:>12} {v['title']}{tag}")
        print(sep)
        vc = sum(1 for v in videos if not v['is_short'])
        sc = sum(1 for v in videos if v['is_short'])
        print(f"总计: {len(videos)} 个（Videos: {vc}, Shorts: {sc}）")
        print("注: 赞数、评论数、收藏数、分享数需要单独请求每个视频页面才能获取")

if __name__ == "__main__":
    main()
