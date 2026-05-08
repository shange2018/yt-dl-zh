#!/bin/bash
# yt-dl-zh.sh - 下载 YouTube 视频 + 中文配音音轨，使用中文文件名
# 用法: ./yt-dl-zh.sh <URL> [输出目录]
#
# 工作流程:
#   1. 用中文 UA 访问 YouTube 页面获取视频标题（优先中文标题）
#   2. 清理标题（去除文件系统不安全字符）
#   3. 用 web_embedded + node 下载视频+中文配音
#   4. 文件名格式: <标题>.mp4

set -euo pipefail

URL="${1:?用法: $0 <YouTube URL> [输出目录]}"
OUTDIR="${2:-$HOME/Downloads}"
PROXY="http://127.0.0.1:2080"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Step 1: 获取视频标题 ──────────────────────────────────────────────
echo "📡 Step 1: 获取视频标题 (中文UA)..."
TITLE=$(python3 "$SCRIPT_DIR/get_yt_title.py" "$URL" 2>/dev/null)

if [ -z "$TITLE" ]; then
    # 回退: 用 yt-dlp 获取标题
    echo "  ⚠️  Python 脚本获取失败，用 yt-dlp 回退..."
    TITLE=$(source /home/shange/.hermes/hermes-agent/venv/bin/activate && \
        yt-dlp --proxy "$PROXY" \
          --extractor-args "youtube:player_client=web_embedded" \
          --js-runtimes "node" \
          --print "%(title)s" \
          --no-download \
          "$URL" 2>/dev/null | head -1)
fi

if [ -z "$TITLE" ]; then
    echo "  ⚠️  无法获取标题，使用视频 ID 作为文件名"
    TITLE=$(echo "$URL" | grep -oP '(?<=v=)[^&]+' || echo "youtube_video")
fi

echo "  📝 标题: $TITLE"

# 检测是否含中文
if echo "$TITLE" | grep -qP '[\x{4e00}-\x{9fff}]'; then
    echo "  ✅ 中文标题"
else
    echo "  ℹ️  非中文标题（保持原语言）"
fi

# ── Step 2: 下载视频 + 中文配音 ───────────────────────────────────────
echo ""
echo "📥 Step 2: 下载视频 + 中文配音音轨..."
echo "  🔧 使用 web_embedded + node JS runtime"

source /home/shange/.hermes/hermes-agent/venv/bin/activate

yt-dlp --proxy "$PROXY" \
  --extractor-args "youtube:player_client=web_embedded" \
  --js-runtimes "node" \
  -f "bv[ext=mp4]+140-16/bv[ext=mp4]+ba[format_note*=original]" \
  --merge-output-format mp4 \
  -o "$OUTDIR/${TITLE}.%(ext)s" \
  "$URL"

echo "  ✅ 视频下载完成"

# ── Step 3: 下载单独中文音轨 (m4a) ──────────────────────────────────────
# echo ""
# echo "🎵 Step 3: 下载单独中文音轨 (m4a)..."
# yt-dlp --proxy "$PROXY" \
#   --extractor-args "youtube:player_client=web_embedded" \
#   --js-runtimes "node" \
#   -f "140-16/140" \
#   --fixup force \
#   -o "$OUTDIR/${TITLE}_zh_audio.%(ext)s" \
#   "$URL" 2>/dev/null && echo "  ✅ 音轨下载完成" || echo "  ⚠️  该视频可能无中文配音音轨"

# ── 完成 ──────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 下载完成！"
echo "📁 输出目录: $OUTDIR"
echo ""
ls -lh "$OUTDIR/${TITLE}"* 2>/dev/null || echo "  (未找到匹配文件)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
