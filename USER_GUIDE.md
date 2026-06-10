# SNKRDUNK Trading Card Scraper 使用说明书

## 目录

1. [项目简介](#1-项目简介)
2. [环境准备](#2-环境准备)
3. [快速上手](#3-快速上手)
4. [运行模式详解](#4-运行模式详解)
5. [输出数据说明](#5-输出数据说明)
6. [断点续爬与增量更新](#6-断点续爬与增量更新)
7. [变更检测（发现新增/变化卡片）](#7-变更检测发现新增变化卡片)
8. [高级用法](#8-高级用法)
9. [常见问题](#9-常见问题)
10. [项目文件结构](#10-项目文件结构)

---

## 1. 项目简介

本项目从 [SNKRDUNK](https://snkrdunk.com/en) 网站爬取所有交易卡（Trading Card）数据。SNKRDUNK 是一个包含宝可梦卡牌（Pokemon TCG）、海贼王卡牌（One Piece TCG）等热门卡牌的交易平台，提供新品和二手卡牌的买卖服务。

### 核心功能

| 功能 | 说明 |
|---|---|
| **批量爬取** | 通过解析网站 sitemap 自动发现所有卡片 URL，批量爬取详情数据 |
| **断点续爬** | 中断后自动从上次进度继续，无需重新爬取 |
| **变更检测** | 对比新旧数据，自动发现新增/删除/价格变化的卡片 |
| **增量更新** | 只爬取新增卡片，与存量数据合并，节省时间 |
| **多格式输出** | 支持 JSON 和 CSV 两种输出格式 |

### 采集字段

每张卡片采集以下字段：

| 字段 | 说明 | 示例 |
|---|---|---|
| `id` | 卡片 ID | `103043` |
| `card_name` | 卡名 | `Mewtwo VSTAR SAR` |
| `brand` | 品牌 | `Pokemon Card Game` |
| `category` | 品类 | `Trading Cards (Single Card)` |
| `min_price` | 最低价(USD) | `228` |
| `min_price_format` | 最低价格式化 | `US $228` |
| `used_listing_count` | 二手 listing 数量 | `4` |
| `used_min_price` | 二手最低价 | `US $228` |
| `listing_count` | listing 总数 | `1` |
| `release_date` | 发布日期 | `2022-12-01T15:00:00Z` |
| `product_code` | 产品编码 | `pkmn-502` |
| `card_type` | 卡片类型 | `single` 或 `box_pack` |
| `thumbnail_url` | 缩略图 URL |
| `description` | Meta 描述 |
| `url` | 商品页 URL |

---

## 2. 环境准备

### 系统要求

- Python 3.9+
- Windows / macOS / Linux

### 安装步骤

```powershell
# 1. 进入项目目录
cd d:\AiProject\SpiderCard

# 2. 创建虚拟环境（推荐）
python -m venv venv

# 3. 激活虚拟环境
# Windows:
.\venv\Scripts\activate
# macOS / Linux:
# source venv/bin/activate

# 4. 安装依赖
pip install -r requirements.txt
```

### 依赖说明

- `requests` — 发送 HTTP 请求
- `beautifulsoup4` — 解析 HTML
- `lxml` — XML/HTML 解析器（性能优于 html.parser）

---

## 3. 快速上手

### 测试模式（验证功能是否正常）

```powershell
.\venv\Scripts\python main.py --test
```

测试模式会：
1. 从 sitemap 发现所有卡片 URL
2. 取前 **5 张** 卡片进行爬取
3. 保存结果到 `data/trading_cards.json`
4. 打印统计信息

预期看到类似输出：
```
[1/5] [INFO] Scraping card 91103: https://snkrdunk.com/en/trading-cards/91103
  -> Charizard VMAX HR | $11184
...
Total cards scraped: 5
```

### 同时输出 JSON 和 CSV

```powershell
.\venv\Scripts\python main.py --test --format both
```

### 完整爬取

```powershell
.\venv\Scripts\python main.py --full
```

首次完整爬取包含两个阶段：
- **Phase 1**: 解析 8 个 gzip sitemap，发现约 **24 万+** 个卡片 URL（耗时约 10 秒）
- **Phase 2**: 逐张爬取卡片详情（每张约 1.5 秒）

> **注意**：完整爬取 24 万张卡片约需 **100 小时**。建议生产使用时降低 `--delay` 值并配合 `--resume` 分多次完成。详见第 8 节。

---

## 4. 运行模式详解

### `--test` 测试模式

```powershell
python main.py --test
# 或带选项:
python main.py --test --format both --delay 0.5
```

- 爬取前 5 张卡片
- 适合验证网络连接、解析逻辑是否正常

### `--full` 完整爬取模式

```powershell
python main.py --full
# 或带选项:
python main.py --full --max 100 --delay 1.0 --format both
```

- 从 sitemap 发现全部卡片并爬取
- 自动保存 URL manifest（用于后续变更检测）
- 使用 `--max` 限制爬取数量

### `--resume` 恢复模式

```powershell
# 自动检测（推荐）
python main.py --resume

# 指定 URL 文件
python main.py --resume data/urls_cache.txt
```

- 从 checkpoint 读取已完成卡片 ID，自动跳过
- 只爬取剩余未完成的卡片
- 适合中断后续爬

### `--check-updates` 检查更新

```powershell
python main.py --check-updates
```

- 仅对比新旧 sitemap URL 列表
- **不爬取任何数据**，速度快（约 10 秒）
- 输出新增和删除的卡片数量及 URL

### `--diff` 差异检测

```powershell
python main.py --diff
# 或指定采样数量:
python main.py --diff --sample 50
```

- 对比 URL 发现新增/删除卡片
- 从已有数据中随机采样 N 张（`--sample`）重新爬取
- 对比价格、listing 数量等关键字段的变化
- 生成详细报告到 `data/diff_report.json`

### `--update` 增量更新

```powershell
python main.py --update
# 或带选项:
python main.py --update --sample 20 --save-interval 50
```

一键完成：
1. 获取最新 sitemap，发现新增卡片
2. 爬取所有新增卡片
3. 采样检测已有卡片的数据变化
4. 合并新旧数据保存
5. 更新 URL manifest

### `--search` 搜索模式

通过官方搜索 API 查找交易卡，**一条请求返回所有匹配结果**（约 1 秒），无需逐个扫描卡片页面。

```powershell
# 搜索名称含 "pikachu" 的卡片
python main.py --search pikachu

# 多关键词搜索（空格分隔）
python main.py --search "sv8 pikachu 136"

# 限制返回数量
python main.py --search charizard --max-matches 10

# 搜索后自动爬取详情（带格式）
python main.py --search "mewtwo vstar" --max-matches 20 --format csv
```

- 调用 SNKRDUNK 官方搜索 API（同网站搜索框使用的接口）
- 返回结果包含：卡片 ID、名称、最低价、listing 数量
- `--max-matches N`：最多返回 N 张（默认 50），实际受 API 限制最多 200
- 搜索完成后询问是否爬取详细数据

#### 搜索示例

| # | 需求 | 命令 | 说明 |
|---|------|------|------|
| 1 | 按系列搜索 | `python main.py --search sv8 --max-matches 100` | 搜索 SV8 系列所有卡片 |
| 2 | 按宝可梦名称 | `python main.py --search pikachu` | 搜所有名称含 pikachu 的卡 |
| 3 | 按宝可梦 + 系列 | `python main.py --search "sv8 pikachu"` | SV8 系列中的皮卡丘 |
| 4 | 按宝可梦 + 编号 | `python main.py --search "pikachu 136"` | 编号 136 的皮卡丘 |
| 5 | 按稀有度 | `python main.py --search SAR --max-matches 100` | 搜索所有 SAR 稀有度卡片 |
| 6 | 精确卡名 | `python main.py --search "charizard ex sar"` | 精确搜索特定卡名 |
| 7 | 按系列 + 编号 | `python main.py --search "sv8 136"` | SV8 系列中编号 136 的卡 |
| 8 | 按宝可梦 + 稀有度 | `python main.py --search "pikachu ur"` | UR 稀有度的皮卡丘 |
| 9 | 按系列 + 稀有度 | `python main.py --search "sv8 sar"` | SV8 系列中的 SAR 卡 |
| 10 | 系列内精确过滤 | `python main.py --search sv8 --kw pikachu --kw 136` | SV8 中同时含 pikachu 和 136 |
| 11 | 系列 + 宝可梦 + 稀有度 | `python main.py --search sv8 --kw pikachu --kw SAR` | SV8 的 pikachu SAR 卡 |
| 12 | 搜完直接爬详情 | `python main.py --search "sv8 pikachu" --format both` | 搜索后输入 y 爬取详细数据 |

> **提示**：`--keyword`（或 `--kw`）可重复使用，对 API 搜索结果做本地二次过滤（AND 逻辑）。先通过 API 快速搜索，再用多个关键词精确过滤，适合"在 sv8 系列中找 pikachu 且编号 136"这种需求。

### `--prices` 价格报告

```powershell
# 从已有数据生成价格汇总
python main.py --prices

# 带 listing 条件级价格（需提供 listing UID 文件）
python main.py --prices --listings-file listings.txt
```

- 统计卡片最低价、二手最低价、Condition 分级价格
- 生成 `data/price_report.json` 详细报告

---

## 6. Web UI 使用

内置 Web 界面，方便搜索和浏览。

### 本地启动

```powershell
.\venv\Scripts\python app.py
```

浏览器打开 http://127.0.0.1:5000

### 功能

- **搜索**: 输入关键词调用搜索 API，勾选卡片爬取详情
- **数据**: 查看已爬取的卡片，支持名称过滤
- **统计**: 卡片总数、价格统计、品牌分布
- **图片**: 点击缩略图可查看大图

### 部署到 CentOS 服务器

```bash
# 上传项目后一键部署
sudo bash deploy_centos.sh

# 访问 http://your-server-ip
```

详见 [DEPLOY.md](DEPLOY.md)。

---

## 7. 输出数据说明

### 输出目录

所有数据默认保存在 `data/` 目录：

```
data/
├── trading_cards.json        ← 完整数据（JSON 格式）
├── trading_cards.csv         ← 完整数据（CSV 格式）
├── checkpoint.txt            ← 已完成卡片 ID（断点续爬用）
├── urls_cache.txt            ← 所有卡片 URL（恢复用）
├── urls_manifest.txt         ← URL 快照（变更检测用）
└── diff_report.json          ← 变更检测报告
```

### JSON 格式示例

```json
{
  "id": "103043",
  "url": "https://snkrdunk.com/en/trading-cards/103043",
  "card_name": "Mewtwo VSTAR SAR",
  "brand": "Pokemon Card Game",
  "category": "Trading Cards (Single Card)",
  "min_price": 228,
  "min_price_currency": "USD",
  "min_price_format": "US $228",
  "listing_count": 1,
  "offer_count": 0,
  "used_listing_count": 4,
  "used_listing_count_text": "4",
  "used_min_price": "US $228",
  "used_min_price_currency": "USD",
  "used_min_price_format": "US $228",
  "release_date": "2022-12-01T15:00:00Z",
  "product_code": "pkmn-502",
  "thumbnail_url": "https://...",
  "card_type": "single",
  "description": "...",
  "image_count": 5
}
```

### CSV 格式

CSV 文件包含除 `image_urls` 之外的所有字段，编码为 UTF-8 with BOM，可直接用 Excel 打开查看中文。

---

## 6. 断点续爬与增量更新

### 工作原理

```
data/checkpoint.txt 内容示例：
91103
91104
91105
```

每成功爬取一张卡片，其 ID 会被追加到 checkpoint 文件。重新运行时，程序会跳过这些 ID。

### 中断后续爬

```powershell
# 假设爬了 10000 张后中断
python main.py --full --delay 1.0  # 运行到中途 Ctrl+C 中断

# 继续爬取
python main.py --resume
# 输出: Checkpoint 发现 10000 张已完成，跳过 10000 张
# 从第 10001 张继续
```

### 定期自动保存中间结果

```powershell
# 每爬取 100 张自动保存一次 JSON 和 CSV
python main.py --full --save-interval 100
```

即使中途崩溃，已有数据也不会丢失。再次使用 `--resume` 继续即可。

---

## 7. 变更检测（发现新增/变化卡片）

### 场景示例

假设你第一次完整爬取后有 240,000 张卡片。一周后网站新增了 50 张新卡，同时已有卡片的
价格发生了变化。

### 步骤一：检查是否有新卡片

```powershell
python main.py --check-updates
```

输出：
```
之前: 240,000 张
现在: 240,050 张
+ 新增: 50 张
- 删除: 0 张
```

### 步骤二：检测价格等数据变化

```powershell
python main.py --diff --sample 100
```

输出：
```
采样 100 张，其中 15 张数据有变化
[103043] Mewtwo VSTAR SAR   min_price: 228 → 245
[91103]  Charizard VMAX HR  used_listing_count: 4 → 6
```

### 步骤三：增量更新

```powershell
python main.py --update --sample 50
```

自动完成：
1. 爬取 50 张新增卡片
2. 采样 50 张旧卡片检测变化
3. 合并新旧数据
4. 更新所有文件

### 差异报告

`data/diff_report.json` 包含完整的变更记录：

```json
{
  "generated_at": "2026-06-09T12:00:00",
  "url_changes": {
    "new_count": 50,
    "removed_count": 0,
    "new_urls": ["https://snkrdunk.com/en/trading-cards/999001", ...]
  },
  "data_changes": {
    "cards_scanned": 100,
    "cards_changed": 15,
    "changed_cards": [
      {
        "id": "103043",
        "card_name": "Mewtwo VSTAR SAR",
        "changed_fields": {
          "min_price": {"old": 228, "new": 245}
        }
      }
    ]
  },
  "new_cards_added": 50
}
```

---

## 8. 高级用法

### 自定义请求延迟

```powershell
# 快速爬取（降低延迟，被 ban 风险略高）
python main.py --full --delay 0.5

# 保守爬取（更安全，但更慢）
python main.py --full --delay 3.0
```

### 自定义输出目录

```powershell
python main.py --full --output ./my_data
```

### 导出为 CSV

```powershell
python main.py --test --format csv
```

### 限量爬取

```powershell
# 只爬取前 50 张
python main.py --full --max 50
```

### 保存 URL 列表后离线爬取

```powershell
# 先保存 URL 列表（不爬取数据）
python main.py --full --max 1 --save-urls

# 之后可以随时用 --resume 爬取
python main.py --resume
```

### 爬取单个 Listing 获取 Condition

```powershell
python -c "
from scraper.card_scraper import CardScraper
s = CardScraper()
d = s.scrape_listing('https://snkrdunk.com/en/trading-cards/used/listings/{listing_id}')
print(d)
"
```

---

## 9. 常见问题

### Q: 爬取速度太慢怎么办？

降低 `--delay` 值。默认 1.5 秒是保守设置，可以尝试 `--delay 0.5` 将爬取速度提高 3 倍。
注意过快的请求可能导致 IP 被封。

### Q: 爬取过程中断了怎么办？

```powershell
python main.py --resume
```

只要没有删除 `data/checkpoint.txt`，程序会自动跳过已完成的卡片，从中断位置继续。

### Q: 如何防止数据丢失？

使用 `--save-interval 100` 每爬取 100 张就自动保存一次。

### Q: 输出乱码 / Excel 打开 CSV 乱码？

CSV 文件使用 UTF-8 with BOM 编码（`utf-8-sig`），Excel 可直接打开。如果仍有乱码，
请在 Excel 中使用"数据 → 自文本/CSV"导入，选择 UTF-8 编码。

### Q: `--update` 和 `--diff` 有什么区别？

- **`--diff`**：只检测变化，不修改已有数据文件
- **`--update`**：检测变化 + 爬取新增卡片 + 合并保存到文件

建议先用 `--diff` 预览变化，再用 `--update` 执行更新。

### Q: 网站结构和字段变了怎么办？

爬虫从页面嵌入的 Vue.js JSON 属性中提取数据。如果网站前端改版，这些属性名（如 `:trading-card`、`:summary`）可能变化，需要更新 `card_scraper.py` 中的解析逻辑。

### Q: 为什么有些卡片没有 `used_listing_count`？

`used_listing_count` 来自 `:summary` 属性，只存在于**单卡**（Single Card）页面。
盒/包（Box/Pack）产品页面没有这个属性，对应字段为空。

---

## 10. 项目文件结构

```
SpiderCard/
├── main.py                     # 主入口脚本
├── requirements.txt            # Python 依赖
├── USER_GUIDE.md               # 本说明文件
│
├── scraper/
│   ├── __init__.py
│   ├── sitemap_parser.py       # Sitemap 解析器
│   ├── card_scraper.py         # 卡片数据爬取器
│   ├── compare_utils.py        # 变更检测工具
│   └── utils.py                # 通用工具函数
│
├── data/                       # 数据输出目录（自动生成）
│   ├── trading_cards.json
│   ├── trading_cards.csv
│   ├── checkpoint.txt
│   ├── urls_cache.txt
│   ├── urls_manifest.txt
│   └── diff_report.json
│
└── venv/                       # Python 虚拟环境
```

### 各模块职责

| 文件 | 职责 |
|---|---|
| `main.py` | CLI 入口，参数解析，调度各模式 |
| `sitemap_parser.py` | 从 sitemap 发现所有卡片 URL（支持 gzip 自动解压） |
| `card_scraper.py` | 爬取单张卡片页面，从 Vue.js 属性中提取结构化数据 |
| `compare_utils.py` | URL 对比、数据对比、变更报告生成 |
| `utils.py` | 文件读写、统计打印等辅助功能 |

---

*生成日期: 2026-06-09*
