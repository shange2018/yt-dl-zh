#!/bin/bash
# yt-channel-list.sh - 获取 YouTube 频道视频列表（Videos + Shorts）
# 用法: ./yt-channel-list.sh <频道名> [数量]
# 输出: 发布日期 | 中文标题（优先），英文标题（回退）

set -euo pipefail

CHANNEL_NAME="${1:?用法: $0 <频道名> [数量]}"
LIMIT="${2:-10}"
PROXY="http://127.0.0.1:2080"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

source /home/shange/.hermes/hermes-agent/venv/bin/activate

TMP_DIR=$(mktemp -d)
trap "rm -rf $TMP_DIR" EXIT

# Step 1: 获取 Videos 列表
echo "📡 [1/3] 获取 Videos..." >&2
yt-dlp --proxy "$PROXY" \
  --extractor-args "youtube:player_client=web_embedded" \
  --js-runtimes "node" \
  --no-download --yes-playlist \
  --print "%(upload_date)s|%(id)s|%(title)s" \
  --playlist-items 1-"$LIMIT" \
  "https://www.youtube.com/@${CHANNEL_NAME}/videos" 2>/dev/null > "$TMP_DIR/videos.txt" || true

# Step 2: 获取 Shorts 列表
echo "📡 [2/3] 获取 Shorts..." >&2
yt-dlp --proxy "$PROXY" \
  --extractor-args "youtube:player_client=web_embedded" \
  --js-runtimes "node" \
  --no-download --yes-playlist \
  --print "%(upload_date)s|%(id)s|%(title)s" \
  --playlist-items 1-"$LIMIT" \
  "https://www.youtube.com/@${CHANNEL_NAME}/shorts" 2>/dev/null > "$TMP_DIR/shorts.txt" || true

# 合并去重排序
cat "$TMP_DIR/videos.txt" "$TMP_DIR/shorts.txt" | \
  awk -F'|' '!seen[$2]++' | sort -t'|' -k1,1r | head -n "$LIMIT" > "$TMP_DIR/all.txt"

TOTAL=$(wc -l < "$TMP_DIR/all.txt")
if [ "$TOTAL" -eq 0 ]; then
    echo "❌ 未获取到视频列表" >&2
    exit 1
fi

# 构建 URL 列表
cut -d'|' -f2 "$TMP_DIR/all.txt" | \
  sed 's/^/https:\/\/www.youtube.com\/watch?v=/' > "$TMP_DIR/urls.txt"

# Step 3: 并发获取中文标题
echo "📡 [3/3] 获取中文标题 ($TOTAL 个)..." >&2
xargs -P 5 -I {} python3 "$SCRIPT_DIR/get_yt_title.py" {} {} \
  < "$TMP_DIR/urls.txt" 2>/dev/null > "$TMP_DIR/zh.txt" || true

# 构建关联数组
declare -A ZH_MAP
while IFS=$'\t' read -r url title; do
    vid=$(echo "$url" | grep -oP '(?<=v=)[^&]+')
    [ -n "$vid" ] && ZH_MAP["$vid"]="$title"
done < "$TMP_DIR/zh.txt"

# 输出
echo "" >&2
printf "%-12s %s\n" "发布日期" "中文标题"
printf "%-12s %s\n" "--------" "--------"

while IFS='|' read -r raw_date vid title; do
    [[ "$raw_date" =~ ^[0-9]{8}$ ]] && d="${raw_date:0:4}-${raw_date:4:2}-${raw_date:6:2}" || d="$raw_date"
    zh="${ZH_MAP[$vid]:-}"
    use="$title"
    if [ -n "$zh" ] && echo "$zh" | grep -q '[一-龥]'; then
        use="$zh"
    fi
    printf "%-12s %s\n" "$d" "$use"
done < "$TMP_DIR/all.txt"

echo "" >&2
echo "✅ 完成！共输出 $TOTAL 个视频" >&2
