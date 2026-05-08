#!/bin/bash
# yt-channel-dl.sh - 下载 YouTube 频道的所有视频（中文配音版）
# 用法: ./yt-channel-dl.sh <频道URL> [输出目录] [选项]
#
# 选项:
#   --limit N      只下载最新 N 个视频
#   --from-date YYYYMMDD  只下载此日期之后的视频
#   --to-date YYYYMMDD    只下载此日期之前的视频
#   --dry-run      只列出视频列表，不下载
#
# 示例:
#   ./yt-channel-dl.sh "https://www.youtube.com/@StokesTwins/videos" ~/Downloads/StokesTwins
#   ./yt-channel-dl.sh "https://www.youtube.com/@StokesTwins" ~/Downloads/StokesTwins --limit 10
#   ./yt-channel-dl.sh "https://www.youtube.com/channel/UCxxx" ~/Downloads/xxx --dry-run

set -euo pipefail

# ── 参数解析 ──────────────────────────────────────────────────────────────
CHANNEL_URL="${1:?用法: $0 <频道URL> [输出目录] [--limit N] [--from-date YYYYMMDD] [--to-date YYYYMMDD] [--dry-run]}"
OUTDIR="${2:-$HOME/Downloads}"
LIMIT=""
FROM_DATE=""
TO_DATE=""
DRY_RUN=false

shift 2 2>/dev/null || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --limit)    LIMIT="$2"; shift 2 ;;
        --from-date) FROM_DATE="$2"; shift 2 ;;
        --to-date)  TO_DATE="$2"; shift 2 ;;
        --dry-run)  DRY_RUN=true; shift ;;
        *)          echo "未知参数: $1"; shift ;;
    esac
done

PROXY="http://127.0.0.1:2080"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 确保输出目录存在
mkdir -p "$OUTDIR"

# ── Step 1: 获取频道信息 ─────────────────────────────────────────────────
echo "📡 Step 1: 获取频道信息..."

# 获取频道名称
CHANNEL_NAME=$(source /home/shange/.hermes/hermes-agent/venv/bin/activate && \
    yt-dlp --proxy "$PROXY" \
      --extractor-args "youtube:player_client=web_embedded" \
      --js-runtimes "node" \
      --flat-playlist \
      --print "%(channel)s" \
      --playlist-items 1 \
      "$CHANNEL_URL" 2>/dev/null | head -1)

if [ -z "$CHANNEL_NAME" ]; then
    CHANNEL_NAME="youtube_channel"
fi
echo "  📺 频道: $CHANNEL_NAME"

# 创建频道专属目录
CHAN_DIR="$OUTDIR/$CHANNEL_NAME"
mkdir -p "$CHAN_DIR"

# ── Step 2: 获取视频列表 ─────────────────────────────────────────────────
echo ""
echo "📋 Step 2: 获取视频列表..."

# 构建 yt-dlp 参数
YT_DLP_ARGS=(
    --proxy "$PROXY"
    --extractor-args "youtube:player_client=web_embedded"
    --js-runtimes "node"
    --flat-playlist
    --print "%(id)s\t%(title)s\t%(upload_date)s"
    --no-download
)

# 日期过滤
if [ -n "$FROM_DATE" ]; then
    YT_DLP_ARGS+=(--dateafter "$FROM_DATE")
fi
if [ -n "$TO_DATE" ]; then
    YT_DLP_ARGS+=(--datebefore "$TO_DATE")
fi

# 获取列表
VIDEOS=$(source /home/shange/.hermes/hermes-agent/venv/bin/activate && \
    yt-dlp "${YT_DLP_ARGS[@]}" "$CHANNEL_URL" 2>/dev/null)

if [ -z "$VIDEOS" ]; then
    echo "  ❌ 未获取到视频列表"
    exit 1
fi

# 统计
TOTAL=$(echo "$VIDEOS" | wc -l)
echo "  📊 共 $TOTAL 个视频"

# 限制数量
if [ -n "$LIMIT" ]; then
    VIDEOS=$(echo "$VIDEOS" | head -n "$LIMIT")
    echo "  🔢 限制: 最新 $LIMIT 个视频"
fi

# 保存列表到文件
LIST_FILE="$CHAN_DIR/video_list.txt"
echo "$VIDEOS" > "$LIST_FILE"
echo "  💾 视频列表已保存: $LIST_FILE"

# 显示前 5 个
echo ""
echo "  📜 视频列表 (前 5 个):"
echo "$VIDEOS" | head -5 | while IFS=$'\t' read -r id title date; do
    echo "    • [$date] $title ($id)"
done

# ── Step 3: 下载视频 ─────────────────────────────────────────────────────
if $DRY_RUN; then
    echo ""
    echo "🔍 Dry-run 模式，跳过下载"
    exit 0
fi

echo ""
echo "📥 Step 3: 开始下载视频..."
echo "  📁 输出目录: $CHAN_DIR"
echo ""

# 下载计数器
COUNT=0
SUCCESS=0
FAIL=0

echo "$VIDEOS" | while IFS=$'\t' read -r video_id video_title upload_date; do
    COUNT=$((COUNT + 1))
    
    # 获取中文标题
    VIDEO_URL="https://www.youtube.com/watch?v=$video_id"
    ZH_TITLE=$(python3 "$SCRIPT_DIR/get_yt_title.py" "$VIDEO_URL" 2>/dev/null || echo "")
    
    if [ -z "$ZH_TITLE" ]; then
        # 回退: 用原始标题清理
        ZH_TITLE=$(echo "$video_title" | sed 's/[\/\\:*?"<>|]/_/g' | sed 's/  */_/g' | sed 's/^_//;s/_$//')
    fi
    
    # 文件名: [日期] 标题.mp4
    FILENAME="${upload_date}_${ZH_TITLE}"
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  🎬 [$COUNT/$TOTAL] $ZH_TITLE"
    echo "  📅 $upload_date | 🆔 $video_id"
    
    # 检查是否已下载
    if ls "$CHAN_DIR/${FILENAME}"* 1>/dev/null 2>&1; then
        echo "  ⏭️  已存在，跳过"
        continue
    fi
    
    # 下载
    source /home/shange/.hermes/hermes-agent/venv/bin/activate
    
    yt-dlp --proxy "$PROXY" \
      --extractor-args "youtube:player_client=web_embedded" \
      --js-runtimes "node" \
      -f "bv[ext=mp4]+140-16/bv[ext=mp4]+ba[format_note*=original]" \
      --merge-output-format mp4 \
      --fixup force \
      --no-overwrites \
      -o "$CHAN_DIR/${FILENAME}.%(ext)s" \
      "$VIDEO_URL" 2>/dev/null && SUCCESS=$((SUCCESS + 1)) || FAIL=$((FAIL + 1))
    
    echo "  ✅ 完成"
    
    # 避免请求过快
    sleep 2
done

# ── 完成 ──────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 下载完成！"
echo "📺 频道: $CHANNEL_NAME"
echo "📁 目录: $CHAN_DIR"
echo "📊 总计: $TOTAL | ✅ 成功: $SUCCESS | ❌ 失败: $FAIL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
