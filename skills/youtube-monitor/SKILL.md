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

## 工作流程

1. **读取频道列表** — 从 `youtuber_list.md` 解析合法频道名
2. **抓取视频列表** — 请求 `youtube.com/@<频道>/videos` 页面，从 `ytInitialData` 解析视频数据
3. **过滤**：
   - 发布日期 >= 20260101
   - 标题含中文字符（正则 `[\u4e00-\u9fff]`）
4. **去重** — 对比 `videos` / `shorts` 表中的 `video_id` / `short_id`，跳过已存在的
5. **插入记录** — 新视频写入 SQLite（`videos` 表存普通视频，`shorts` 表存 Shorts）
6. **下载** — yt-dlp 下载 MP4 + 中文音轨，合并，以中文标题命名

## 数据库 Schema

### videos 表

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| yountuber | TEXT | 频道名 |
| video_id TEXT UNIQUE | YouTube 视频 ID |
| title | TEXT | 中文标题 |
| duration | TEXT | 时长 (如 58:33) |
| views | TEXT | 播放量 (如 1150万) |
| pub_date | TEXT | 发布日期 (YYYYMMDD) |
| downloaded | INTEGER | 是否已下载 (0/1) |
| file_path | TEXT | 下载文件路径 |
| created_at | TEXT | 记录创建时间 |

### shorts 表

结构相同，`video_id` 改为 `short_id`。

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

## 注意事项

- 页面一次返回约 30 个视频，翻页通过 continuation token 实现
- 发布时间从相对时间（"5天前"）转换，误差 1~3 天
- 文件大小无法从页面获取，不存储
- 收藏数/分享数 YouTube 不公开，无法获取
