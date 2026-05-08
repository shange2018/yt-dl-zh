# yt-dl-zh

下载 YouTube 视频 + 中文配音音轨，自动获取中文标题作为文件名。

## 功能

- 🎬 下载 YouTube 视频并自动选择中文配音音轨合并
- 🌏 优先获取视频中文标题（针对中文 UA），回退到原始标题
- 🔧 使用 `web_embedded` + `node` JS runtime 解决 dubbed 音轨 403 问题

## 前置条件

- `yt-dlp` + `ffmpeg`
- `node` v24+
- Python 3.11+
- `yt-dlp-ejs` 包（`pip install yt-dlp-ejs`）

## 用法

```bash
./scripts/yt-dl-zh.sh <YouTube URL> [输出目录]
```

示例：
```bash
./scripts/yt-dl-zh.sh "https://www.youtube.com/shorts/oT0YAym1ZjM" ~/Downloads
```

## 文件

- `scripts/yt-dl-zh.sh` — 主下载脚本
- `scripts/get_yt_title.py` — 获取视频中文标题

