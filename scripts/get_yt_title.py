#!/usr/bin/env python3
"""
批量获取 YouTube 视频的中文标题（串行请求，带超时）。
用法: python3 get_yt_title.py <URL> [URL2] ...
或:   cat urls.txt | python3 get_yt_title.py
输出: URL <TAB> 中文标题
"""

import sys
import re
import json
import urllib.request

PROXY = "http://127.0.0.1:2080"


def fetch_page(url):
    proxy_handler = urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    with opener.open(req, timeout=15) as resp:
        return resp.read().decode('utf-8', errors='ignore')


def get_zh_title(url):
    try:
        html = fetch_page(url)
    except Exception:
        return ""

    # ytInitialData
    m = re.search(r'ytInitialData\s*=\s*({.*?});', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            overlay = data.get('overlay', {})
            reel = overlay.get('reelPlayerOverlayRenderer', {})

            # shortsVideoTitleViewModel
            metapanel = reel.get('metapanel', {}).get('reelMetapanelViewModel', {})
            for item in metapanel.get('metadataItems', []):
                content = item.get('shortsVideoTitleViewModel', {}).get('text', {}).get('content', '')
                if content and has_zh(content):
                    return content

            # videoDescriptionHeaderRenderer
            for panel in data.get('engagementPanels', []):
                items = panel.get('engagementPanelSectionListRenderer', {}).get('content', {}).get('structuredDescriptionContentRenderer', {}).get('items', [])
                for item in items:
                    runs = item.get('videoDescriptionHeaderRenderer', {}).get('title', {}).get('runs', [])
                    text = ''.join(r.get('text', '') for r in runs)
                    if text and has_zh(text):
                        return text

            # pageHeaderViewModel
            for panel in data.get('engagementPanels', []):
                grid = panel.get('engagementPanelSectionListRenderer', {}).get('content', {}).get('richGridRenderer', {})
                content = grid.get('pageHeaderViewModel', {}).get('title', {}).get('dynamicTextViewModel', {}).get('text', {}).get('content', '')
                if content and has_zh(content):
                    return content
        except:
            pass

    # fallback: og:title
    m = re.search(r'og:title" content="([^"]+)"', html)
    if m:
        return m.group(1)
    return ""


def has_zh(text):
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def main():
    urls = list(sys.argv[1:]) if len(sys.argv) > 1 else []
    if not sys.stdin.isatty():
        urls += [l.strip() for l in sys.stdin if l.strip()]
    if not urls:
        print("Usage: get_yt_title.py <URL> ...", file=sys.stderr)
        sys.exit(1)

    from concurrent.futures import ThreadPoolExecutor, as_completed
    results = {}
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(lambda u: (u, get_zh_title(u)), u): u for u in urls}
        for f in as_completed(futures):
            url, title = f.result()
            results[url] = title

    for url in urls:
        print(f"{url}\t{results.get(url, '')}")


if __name__ == '__main__':
    main()
