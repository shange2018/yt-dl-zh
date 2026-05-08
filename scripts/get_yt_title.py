#!/usr/bin/env python3
"""
获取 YouTube 视频的中文标题，用于文件名。
优先从 ytInitialData 中提取 Shorts 的中文标题，
回退到 ytInitialPlayerResponse 的 videoDetails.title。

用法: python3 get_yt_title.py <URL>
输出: 清理后的标题字符串（适合做文件名）
"""

import sys
import re
import json
import urllib.request
import urllib.error

PROXY = "http://127.0.0.1:2080"


def fetch_page(url: str) -> str:
    """用中文 UA 获取 YouTube 页面"""
    proxy_handler = urllib.request.ProxyHandler({
        'http': PROXY,
        'https': PROXY,
    })
    opener = urllib.request.build_opener(proxy_handler)
    
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    })
    
    with opener.open(req, timeout=30) as resp:
        return resp.read().decode('utf-8', errors='ignore')


def extract_zh_title_from_yt_initial_data(html: str) -> str | None:
    """
    从 ytInitialData 中提取 Shorts 的中文标题。
    路径: overlay.reelPlayerOverlayRenderer.metapanel.reelMetapanelViewModel.metadataItems[N].shortsVideoTitleViewModel.text.content
    """
    m = re.search(r'ytInitialData\s*=\s*({.*?});', html, re.DOTALL)
    if not m:
        return None
    
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    
    # 导航到 reelPlayerOverlayRenderer
    overlay = data.get('overlay', {})
    reel_overlay = overlay.get('reelPlayerOverlayRenderer', {})
    
    # 方法1: metapanel.reelMetapanelViewModel.metadataItems[].shortsVideoTitleViewModel
    metapanel = reel_overlay.get('metapanel', {})
    reel_metapanel = metapanel.get('reelMetapanelViewModel', {})
    metadata_items = reel_metapanel.get('metadataItems', [])
    
    for item in metadata_items:
        shorts_title = item.get('shortsVideoTitleViewModel', {})
        text = shorts_title.get('text', {})
        content = text.get('content', '')
        if content and contains_chinese(content):
            return content
    
    # 方法2: engagementPanels[].structuredDescriptionContentRenderer.items[].videoDescriptionHeaderRenderer.title
    panels = data.get('engagementPanels', [])
    for panel in panels:
        section = panel.get('engagementPanelSectionListRenderer', {})
        content = section.get('content', {})
        desc_content = content.get('structuredDescriptionContentRenderer', {})
        items = desc_content.get('items', [])
        for item in items:
            header = item.get('videoDescriptionHeaderRenderer', {})
            title = header.get('title', {})
            runs = title.get('runs', [])
            if runs:
                text = ''.join(r.get('text', '') for r in runs)
                if text and contains_chinese(text):
                    return text
    
    # 方法3: engagementPanels[].pageHeaderViewModel.title.dynamicTextViewModel.text.content
    for panel in panels:
        section = panel.get('engagementPanelSectionListRenderer', {})
        content = section.get('content', {})
        grid = content.get('richGridRenderer', {})
        header = grid.get('pageHeaderViewModel', {})
        title_vm = header.get('title', {})
        dynamic_text = title_vm.get('dynamicTextViewModel', {})
        text = dynamic_text.get('text', {})
        content = text.get('content', '')
        if content and contains_chinese(content):
            return content
    
    return None


def contains_chinese(text: str) -> bool:
    """检查字符串是否包含中文字符"""
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def get_yt_title(url: str) -> str:
    """获取 YouTube 视频的中文标题"""
    html = fetch_page(url)
    
    # 优先: ytInitialData 中的中文标题（Shorts）
    title = extract_zh_title_from_yt_initial_data(html)
    if title:
        return clean_filename(title)
    
    # 回退: ytInitialPlayerResponse.videoDetails.title
    m = re.search(r'ytInitialPlayerResponse\s*=\s*({.*?});', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            title = data.get('videoDetails', {}).get('title', '')
            if title:
                return clean_filename(title)
        except json.JSONDecodeError:
            pass
    
    # 回退: og:title
    m = re.search(r'og:title" content="([^"]+)"', html)
    if m:
        return clean_filename(m.group(1))
    
    # 回退: <title>
    m = re.search(r'<title>([^<]+)</title>', html)
    if m:
        title = m.group(1).replace(' - YouTube', '').strip()
        if title:
            return clean_filename(title)
    
    raise ValueError(f"无法从页面提取标题: {url}")


def clean_filename(title: str) -> str:
    """清理标题，使其适合做文件名"""
    # 替换文件系统不安全的字符
    unsafe = r'[<>:"/\\|?*]'
    title = re.sub(unsafe, '_', title)
    # 替换多个空格/下划线为单个
    title = re.sub(r'[\s_]+', '_', title)
    # 去掉首尾下划线和空格
    title = title.strip('_').strip()
    # 限制长度（避免文件名过长）
    if len(title) > 200:
        title = title[:200]
    return title


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"用法: {sys.argv[0]} <YouTube URL>")
        sys.exit(1)
    
    url = sys.argv[1]
    try:
        title = get_yt_title(url)
        print(title)
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
