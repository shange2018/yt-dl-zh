---
name: youtube-monitor
description: YouTube 频道监控下载 — 自动扫描频道新视频，过滤中文标题，用 yt-dlp 下载 MP4+中文音轨并合并
---

# YouTube 监控下载技能

## 概述

定期扫描指定 YouTube 频道的最新视频，过滤出有中文标题且发布日期在 2026-01-01 之后的新视频，自动下载 MP4 视频+中文音轨并合并，以中文标题命名文件。

## 文件结构

```
~/.hermes/scripts/
├── yt_monitor.py           # 主脚本
├── youtuber_list.md        # 频道列表
└── videos_shorts_list.db   # SQLite 数据库（自动生成）
```

下载文件保存到 `~/youtube-downloads/`

## 使用方法

### 添加监控频道

编辑 `~/.hermes/scripts/youtuber_list.md`，在「活跃频道」下添加频道名（不含 `@`）：

```markdown
## 活跃频道

- StokesTwins
- AnotherChannel
```

频道名规则：只含英文、数字、下划线、连字符（正则 `^[A-Za-z0-9_-]+$`），其他行（注释、描述文字）自动跳过。

### 扫描（不下载）

```bash
cd ~/.hermes/scripts && python3 yt_monitor.py --dry-run
```

### 扫描 + 下载

```bash
cd ~/.hermes/scripts && python3 yt_monitor.py
```

### 只处理指定频道

```bash
python3 yt_monitor.py --channel StokesTwins --dry-run
```

### 只输出列表（不下载不入库）

```bash
python3 yt_monitor.py --list
```

## 工作流程

1. **读取频道列表** — 从 `youtuber_list.md` 解析合法频道名（跳过注释、描述行）
2. **抓取视频列表** — 请求 `youtube.com/@<频道>/videos` 页面，从 `ytInitialData` 解析视频数据
3. **过滤**：
   - 发布日期 >= 20260101（可配置 `MIN_DATE`）
   - 标题含中文字符（正则 `[\u4e00-\u9fff]`）
4. **去重** — 对比 `videos` / `shorts` 表，`downloaded=1` 的记录跳过；`downloaded=0` 或 `2` 的会重新下载
5. **插入记录** — 新视频写入 SQLite（`videos` 表存普通视频，`shorts` 表存 Shorts）
6. **下载** — yt-dlp 下载 MP4 + 中文音轨，合并，以中文标题命名
7. **更新状态** — 下载成功标记 `downloaded=1`，失败标记 `downloaded=2`

## 数据库 Schema

### videos 表

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| youtuber | TEXT | 频道名 |
| video_id | TEXT UNIQUE | YouTube 视频 ID |
| title | TEXT | 中文标题 |
| duration | TEXT | 时长 (如 58:33) |
| views | TEXT | 播放量 (如 1150万) |
| pub_date | TEXT | 发布日期 (YYYYMMDD) |
| downloaded | INTEGER | 0=待下载, 1=已下载, 2=下载失败 |
| file_path | TEXT | 下载文件路径 |
| created_at | TEXT | 记录创建时间 |

### shorts 表

结构相同，`video_id` 改为 `short_id`。

## 去重逻辑

```sql
SELECT 1 FROM videos WHERE video_id = ? AND downloaded = 1
```

- `downloaded=0`：新记录，未下载 → 会触发下载
- `downloaded=1`：已下载成功 → 跳过
- `downloaded=2`：下载失败 → 下次运行会重试

## 依赖

- Python 3.10+
- yt-dlp (with yt-dlp-ejs)
- node v24+ (JS 签名，用于下载中文音轨)
- ffmpeg (合并音视频)
- 代理 `http://127.0.0.1:2080`（可配置）

## 配置

在 `yt_monitor.py` 顶部修改常量：

```python
PROXY     = "http://127.0.0.1:2080"   # 代理地址
MIN_DATE  = "20260101"                 # 最早发布日期
DOWNLOAD_DIR = "~/youtube-downloads"   # 下载目录
```

## 关键技术细节

### 页面数据结构 (YouTube 2024+ 新 UI)

```
ytInitialData
  .contents.twoColumnBrowseResultsRenderer
    .tabs[1].tabRenderer.content.richGridRenderer.contents[]
      .richItemRenderer.content.lockupViewModel
        .contentId                    → 视频 ID
        .contentType                 → LOCKUP_CONTENT_TYPE_VIDEO / SHORTS
        .metadata.lockupMetadataViewModel
          .title.content             → 中文标题
          .metadata.contentMetadataViewModel.metadataRows[0]
            .metadataParts[0].text.content  → 播放量
            .metadataParts[1].text.content  → 相对发布时间
        .contentImage.thumbnailViewModel.overlays[0]
          .thumbnailBottomOverlayViewModel.badges[0]
            .thumbnailBadgeViewModel.text  → 时长
```

### 发布时间转换

YouTube 页面只提供相对时间（"5天前"），脚本用 `datetime.now() - timedelta` 转换为绝对日期：
- `小时前` → 精确
- `天前` → 精确
- `周前` → 精确
- `个月前` → 近似（±30天/月）
- `年前` → 近似（±365天/年）

### 翻页机制

首页面约 30 个视频，通过 `continuationItemRenderer.continuationEndpoint.continuationCommand.token` 翻页，调用 `youtubei/v1/browse` API。

## 已知限制

- 页面抓取方式无法获取 like_count / comment_count（页面 HTML 不暴露）
- 发布时间转换有 1~3 天误差（"个月前"/"年前"）
- 文件大小无法从页面获取
- 收藏数/分享数 YouTube 不公开

## 故障排除

| 问题 | 原因 | 解决 |
|------|------|------|
| `yountuber` 列名错误 | 旧数据库列名拼写错误 | 删除 `videos_shorts_list.db` 重建 |
| 频道列表解析出非频道名 | 描述行被误读 | 脚本已用正则 `^[A-Za-z0-9_-]+$` 过滤 |
| 下载失败标记 | 网络超时或代理问题 | 脚本自动标记 `downloaded=2`，下次重试 |
| f-string 破坏 SQL | `f"""` 中的 `{id}` 被解析 | 建表 SQL 用普通 `"""`，只有动态表名/列名用 `f"""` |

## 相关技能

- `youtube-channel-list` — 仅列出频道视频（不下载）
- `youtube-download` — 下载单个视频/播放列表
- GitHub repo: https://github.com/shange2018/yt-dl-zh
