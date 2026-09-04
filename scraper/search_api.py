"""
Search API - SNKRDUNK 新站 (snkrdunk.com) 交易卡搜索与价格查询

说明：
  - snkrdunk.com/en 旧站已下线，商品与价格统一位于日文站。
  - 搜索列表页: https://snkrdunk.com/search?keywords=...&itemConditions=...&itemSizes=...&page=N
    页面为 Next.js SSR，商品数据内嵌在 RSC Flight payload 中，本模块负责解码提取。
  - 商品详情节: https://snkrdunk.com/apparels/{id}
    页面内嵌每个「商品状态」chips（conditionId / text / usedMinPrice / hasListing）。
  - 在售清单 API: https://snkrdunk.com/v1/apparels/{id}/used?conditionIds=...
  - 页面原始价格单位为日元(¥)；本模块一律按 scraper.fx 提供的最新汇率
    （自动抓取并存入 fx_rate 表）换算为港币(HK$)后返回 / 入库，不存日元。

对外保留的接口（兼容旧调用方）：
  search_trading_cards(keyword, max_results, item_condition, item_size)
  fetch_condition_prices(card_id, card_data=None, timeout=10)
  print_search_results / save_search_results / format_condition_summary
"""

import copy
import json
import os
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from scraper import fx  # 汇率 JPY→HKD（数据库 + 自动抓取）

BASE_URL = "https://snkrdunk.com"
SEARCH_URL = f"{BASE_URL}/search"
DETAIL_URL = f"{BASE_URL}/apparels/{{id}}"
USED_LISTINGS_URL = f"{BASE_URL}/v1/apparels/{{product_id}}/used"
# 交易履历 API（v3）：商品需用 productCatalogId（非 apparels id），
# variant_id 代表「枚数」；不带 variant_id 时默认回传 1枚 的交易与 filters.variants.options
TRADING_HISTORY_URL = f"{BASE_URL}/v3/products/{{product_id}}/trading-history"

# 详情页抓取结果的进程内缓存（同一会话内反复打开/搜索同一张卡时命中，避免重复打 SNKRDUNK）
_DETAIL_CACHE: Dict[str, tuple] = {}
_DETAIL_CACHE_TTL = 300   # 5 分钟
_DETAIL_LOCK = threading.Lock()

# 兼容旧版 OpenSSL 的 SSL 上下文
_SSL_CTX = ssl.create_default_context()
try:
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE
except Exception:
    pass

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.5",
    "Accept-Language": "ja,en;q=0.8",
}

# ============================================================
#  搜索页筛选项（来源: /v3/search/filter 与搜索页 filterValues）
# ============================================================

# 商品の状態（itemConditions）：slug -> 显示名
CONDITION_OPTIONS: List[Dict[str, str]] = [
    {"value": "brand_new_sealed", "label": "S 新品・未開封"},
    {"value": "like_new", "label": "A"},
    {"value": "minor_scratches", "label": "B"},
    {"value": "moderate_scratches", "label": "C"},
    {"value": "significant_damage", "label": "D"},
    {"value": "psa_10", "label": "PSA 10"},
    {"value": "psa_9", "label": "PSA 9"},
    {"value": "psa_8_below", "label": "PSA 8以下"},
    {"value": "bgs_10_black", "label": "BGS 10 BL"},
    {"value": "bgs_10_gold", "label": "BGS 10 GL"},
    {"value": "bgs_9_5", "label": "BGS 9.5"},
    {"value": "bgs_9_below", "label": "BGS 9以下"},
    {"value": "ars_10_plus", "label": "ARS 10+"},
    {"value": "ars_10", "label": "ARS 10"},
    {"value": "ars_9", "label": "ARS 9"},
    {"value": "ars_8_below", "label": "ARS 8以下"},
    {"value": "other_grading_company", "label": "他鑑定品"},
]

# 枚数・個数（itemSizes）
SIZE_OPTIONS: List[Dict[str, str]] = [
    {"value": f"quantity_{n}", "label": f"{n}枚"} for n in range(1, 20)
] + [{"value": "quantity_20_or_above", "label": "20枚以上"}]

# 详情页 chips 的文本 → 规范化等级（与旧站/数据库使用的等级命名保持一致）
GRADE_NORMALIZE = {
    "PSA10": "PSA 10",
    "PSA9": "PSA 9",
    "PSA8以下": "PSA 8 or under",
    "BGS10 BL": "BGS 10 BL",
    "BGS10 GL": "BGS 10 GL",
    "BGS9.5": "BGS 9.5",
    "BGS9以下": "BGS 9 or under",
    "ARS10+": "ARS 10+",
    "ARS10": "ARS 10",
    "ARS9": "ARS 9",
    "ARS8以下": "ARS 8 or under",
    "他鑑定品": "Other",
}


def normalize_grade(text: str) -> str:
    """把详情页 chip 文本转成统一的等级名"""
    t = (text or "").strip()
    return GRADE_NORMALIZE.get(t, t)


# ============================================================
#  HTTP 工具
# ============================================================

def _urlopen(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers=_HEADERS)
    return urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout)


def fetch_text(url: str, timeout: int = 30) -> Optional[str]:
    try:
        with _urlopen(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"[ERROR] HTTP {e.code} {url}")
        return None
    except Exception as e:
        print(f"[ERROR] 请求失败 {url}: {e}")
        return None


def fetch_json(url: str, timeout: int = 30) -> Optional[Dict]:
    text = fetch_text(url, timeout=timeout)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"[ERROR] 非 JSON 响应: {url}")
        return None


# ============================================================
#  RSC Flight payload 解码
# ============================================================

def _decode_flight_chunks(html: str) -> List[str]:
    """把 Next.js RSC 内嵌数据块解码成可读文本"""
    out: List[str] = []
    pat = re.compile(r'\.push\(\[(\d+),"((?:[^"\\]|\\.)*)"\]\)')
    for m in pat.finditer(html):
        try:
            chunk = json.loads('"' + m.group(2) + '"')
            out.append(chunk)
        except Exception:
            continue
    return out


def _first_json_object(text: str, key: str) -> Optional[Dict]:
    """找到 key 首次出现且冒号后为 { 的 JSON 对象并解析"""
    dec = json.JSONDecoder()
    for m in re.finditer(re.escape('"') + key + re.escape('"'), text):
        colon = text.find(":", m.end())
        if colon < 0:
            continue
        s = colon + 1
        while s < len(text) and text[s] in " \t\r\n":
            s += 1
        if text[s:s + 1] != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text, s)
            return obj
        except Exception:
            continue
    return None


def _decode_rsc_text(html: str) -> str:
    """把 RSC flight payload 解码后拼接成一段文本，便于 JSON 定位"""
    return "\n".join(_decode_flight_chunks(html))


def _enclosing_json_object(text: str, marker: str) -> Optional[Dict]:
    """
    定位 marker 首次出现的位置，并向前回溯找到包含它的完整 JSON 对象。
    用于从解码后的 RSC 文本里取出如 productNumber 所在的大对象。
    """
    pos = text.find(marker)
    if pos < 0:
        return None
    dec = json.JSONDecoder()
    start = text.rfind("{", 0, pos)
    for _ in range(500):
        if start < 0:
            return None
        try:
            obj, _ = dec.raw_decode(text, start)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
        start = text.rfind("{", 0, start)
    return None


def _parse_product_summary(html: str) -> Dict:
    """
    从详情页（apparels/{id}）的 RSC 数据中提取商品摘要：
      productCatalogId / productNumber / name(英) / localizedName(日) / brand /
      primaryMedia.imageUrl / 在售数
    """
    text = _decode_rsc_text(html)
    obj = _enclosing_json_object(text, '"productNumber"')
    if not obj:
        return {}
    brands = obj.get("brands") or []
    media = obj.get("primaryMedia") or {}
    return {
        "catalog_id": obj.get("productCatalogId"),
        "product_code": str(obj.get("productNumber", "") or ""),
        "name": str(obj.get("name", "") or ""),
        "name_ja": str(obj.get("localizedName", "") or ""),
        "brand": str(brands[0].get("name", "")) if brands else "",
        "image_url": str(media.get("imageUrl", "") or ""),
        "listing_count": obj.get("usedListingCount"),
        "sale_count_text": str(obj.get("usedListingCountText", "") or ""),
    }


# ============================================================
#  搜索
# ============================================================

def _product_id_from_link(link: str) -> str:
    m = re.search(r"/apparels/(\d+)", link or "")
    return m.group(1) if m else ""


def _normalize_search_product(p: Dict) -> Dict:
    link = p.get("link", "") or ""
    pid = _product_id_from_link(link)
    sale_jpy = p.get("salePrice")
    sale_hkd = fx.jpy_to_hkd(sale_jpy) if sale_jpy is not None else None
    return {
        "id": pid,
        "card_name": p.get("title", "") or p.get("name", ""),
        "title": p.get("title", "") or p.get("name", ""),
        "url": link if link.startswith("http") else f"{BASE_URL}{link}",
        "min_price": sale_hkd,
        "min_price_format": fx.format_hkd(sale_hkd),
        "listing_count": p.get("stockFromGeneralUsers", "0"),
        "all_listing_count": "",
        "offer_count": p.get("favoriteCount", "0"),
        "thumbnail_url": p.get("imageUrl", ""),
        "release_date": "",
        "product_id": p.get("productId", ""),
        # 搜索 payload 的 productId 即 productCatalogId，
        # 详情接口可用它并行拉取交易履历，避免二次串行请求
        "catalog_id": p.get("productId", ""),
        "product_number": "",
        "is_trading_card": True,
        "_source": "search",
    }


def search_trading_cards(
    keyword: str,
    max_results: int = 50,
    per_page: int = 30,
    page_limit: int = 20,
) -> List[Dict]:
    """
    通过 snkrdunk.com/search 搜索商品（固定枚数 = 1枚 quantity_1，不筛商品状态）。

    Args:
        keyword: 关键词（空格分隔多个词自动以 + 连接）
        max_results: 最多返回结果数
        per_page: 每页条数（页面固定 30）
        page_limit: 最多翻页数，防止无限抓取

    Returns:
        商品列表（价格已换算为港币）
    """
    kw = keyword.strip()
    # 每次搜索前尝试抓取一次新汇率（成功会写库），失败则用库内最新
    fx.get_hkd_rate(refresh=True)
    results: List[Dict] = []
    page = 1
    total_pages: Optional[int] = None

    while len(results) < max_results and page <= page_limit:
        # 固定枚数 = 1枚（quantity_1）；空格需编码为 %20，不能先替换成 + 再用 quote
        # （quote 会把 + 转成 %2B，导致多词关键词搜不到）
        q = f"keywords={urllib.request.quote(kw)}&itemSizes=quantity_1&page={page}"
        url = f"{SEARCH_URL}?{q}"

        html = fetch_text(url)
        if not html:
            break
        text = "\n".join(_decode_flight_chunks(html))
        obj = _first_json_object(text, "serverSearchData")
        if not obj:
            print(f"[WARN] 搜索页无法解析（第 {page} 页）")
            break

        products = obj.get("products") or []
        page_info = obj.get("pageInfo") or {}
        if total_pages is None:
            total_pages = int(page_info.get("totalPages") or 1)
            print(f"[INFO] 搜索 '{keyword}': 共 {page_info.get('totalItems', '?')} 条 / {total_pages} 页")

        for p in products:
            row = _normalize_search_product(p)
            if row["id"] and not any(x["id"] == row["id"] for x in results):
                results.append(row)
            if len(results) >= max_results:
                break

        if not products or page >= total_pages:
            break
        page += 1

    results = results[:max_results]
    return results


def print_search_results(results: List[Dict], keyword: str):
    """打印搜索结果摘要"""
    print(f"\n{'=' * 60}")
    print(f"搜索结果: '{keyword}' - {len(results)} 条")
    print(f"{'=' * 60}")
    for i, r in enumerate(results):
        name = r.get("card_name", "")[:65]
        price = r.get("min_price")
        print(f"  [{i + 1}] [{r['id']}] {name}")
        print(f"      最低价: {fx.format_hkd(price)}  |  url: {r.get('url', '')}")


def save_search_results(results: List[Dict], filepath: str):
    """保存搜索结果到文件"""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  搜索列表已保存: {filepath}")


# ============================================================
#  详情页商品状态价格
# ============================================================

def _parse_condition_chips(html: str) -> List[Dict]:
    """
    从详情页 HTML 中解析每个「商品状态」chip。
    返回 [{condition_id, condition_code, text, used_min_price, has_listing}, ...]
    """
    chips = []
    pat = re.compile(r'\{"conditionId":\s*\d+[^{}]*\}')
    for m in pat.finditer(html):
        frag = m.group(0)
        try:
            o = json.loads(frag)
        except Exception:
            continue
        if "conditionId" not in o:
            continue
        chips.append({
            "condition_id": o.get("conditionId"),
            "condition_code": o.get("conditionCode", ""),
            "text": o.get("text", ""),
            "used_min_price": o.get("usedMinPrice"),
            "has_listing": bool(o.get("hasListing", False)),
        })
    return chips


def _conditions_from_chips(chips: List[Dict]) -> Dict[str, Dict]:
    """把详情页 chips 转成 { 等级: {price(HKD), format, count, has_listing, error} }"""
    result: Dict[str, Dict] = {}
    for chip in chips:
        grade = normalize_grade(chip["text"])
        price_jpy = chip["used_min_price"]
        price_hkd = fx.jpy_to_hkd(price_jpy) if price_jpy is not None else None
        result[grade] = {
            "price": price_hkd,
            "format": fx.format_hkd(price_hkd),
            "count": 1 if chip["has_listing"] and price_hkd is not None else 0,
            "has_listing": bool(chip.get("has_listing", False)),
            "error": None,
        }
    return result


def fetch_latest_sold_prices(catalog_id, timeout: int = 12) -> Optional[Dict[str, Dict]]:
    """
    通过 trading-history API（v3/products/{productCatalogId}/trading-history）抓取
    该商品「1枚」的最新已售成交（默认 variant 即 1枚；若有变才显式带 variant_id）。

    Returns:
        { 等级: {"sold_price": HKD, "sold_format": "HK$..", "sold_at": ISO时间, ...} }
        无交易或失败时返回 None/{}。
    """
    if not catalog_id:
        return None
    url = f"{TRADING_HISTORY_URL.format(product_id=catalog_id)}?range=all"
    payload = fetch_json(url, timeout=timeout)
    if not payload:
        return None

    trades = payload.get("trades") or []

    # 枚数在返回数据的 filters.variants.options / trades[].label 里；只采计 1枚
    one_id = None
    try:
        for o in (payload.get("filters") or {}).get("variants", {}).get("options", []):
            if str(o.get("name") or "").strip().startswith("1"):
                one_id = o.get("id")
                break
    except Exception:
        pass

    labels = {str(t.get("label") or "") for t in trades if t.get("label")}
    # 默认交易若非 1枚（罕见），用 options 中 1枚 的 variant_id 再取一次
    if labels and labels != {"1枚"} and one_id:
        payload = fetch_json(url + f"&variant_id={one_id}", timeout=timeout)
        if payload:
            trades = payload.get("trades") or []

    latest: Dict[str, tuple] = {}  # title -> (soldAt, price_jpy)
    for t in trades:
        if t.get("label") and str(t.get("label")) != "1枚":
            continue
        title = str(t.get("title") or "").strip()
        if not title:
            continue
        sold_at = str(t.get("soldAt") or "")
        if title not in latest or sold_at > latest[title][0]:
            latest[title] = (sold_at, t.get("price"))

    result: Dict[str, Dict] = {}
    for title, (sold_at, price_jpy) in latest.items():
        price_hkd = fx.jpy_to_hkd(price_jpy) if price_jpy is not None else None
        grade = normalize_grade(title)
        result[grade] = {
            "sold_price": price_hkd,
            "sold_format": fx.format_hkd(price_hkd),
            "sold_price_jpy": price_jpy,
            "sold_at": sold_at,
        }
    return result


def _cache_get_detail(card_id: str) -> Optional[Dict]:
    with _DETAIL_LOCK:
        ent = _DETAIL_CACHE.get(card_id)
        if ent and time.time() - ent[0] < _DETAIL_CACHE_TTL:
            return ent[1]
    return None


def _cache_put_detail(card_id: str, data: Dict):
    with _DETAIL_LOCK:
        if len(_DETAIL_CACHE) > 600:
            _DETAIL_CACHE.clear()
        _DETAIL_CACHE[card_id] = (time.time(), data)


def fetch_card_detail(card_id: str, timeout: int = 15, catalog_id=None, fresh: bool = False) -> Optional[Dict]:
    """
    从详情页 https://snkrdunk.com/apparels/{id} 抓取卡牌详情：
    商品摘要（品番/名称/品牌/主图/在售数）+ 各成色最低售价（HKD）+
    各成色「最新已售(1枚)」（trading-history）。

    Args:
        card_id: apparels 商品 ID
        catalog_id: 若已知 productCatalogId（搜索 payload 的 productId），
                    apparels 页面与交易履历将并行抓取，加速详情加载
        fresh: True 时忽略进程内缓存，强制重新抓取（写库/价格更新流程使用）
    """
    key = str(card_id)
    cached = None if fresh else _cache_get_detail(key)
    if cached is not None:
        return copy.deepcopy(cached)

    data = _fetch_detail_impl(key, timeout=timeout, catalog_id=catalog_id)
    if data is not None:
        _cache_put_detail(key, data)
    return data


def _fetch_detail_impl(card_id: str, timeout: int, catalog_id=None) -> Optional[Dict]:
    url = DETAIL_URL.format(id=card_id)
    html = None
    sold_map = None

    if catalog_id:
        # 已知 catalog_id：详情页与交易履历并行拉取（各开一个线程）
        bag: Dict = {}

        def _get_html():
            bag["html"] = fetch_text(url, timeout=timeout)

        def _get_sold():
            bag["sold"] = fetch_latest_sold_prices(str(catalog_id), timeout=timeout)

        t1 = threading.Thread(target=_get_html)
        t2 = threading.Thread(target=_get_sold)
        t1.start(); t2.start(); t1.join(); t2.join()
        html = bag.get("html")
        sold_map = bag.get("sold")
    else:
        html = fetch_text(url, timeout=timeout)

    if not html:
        return None

    conditions = _conditions_from_chips(_parse_condition_chips(html))
    summary = _parse_product_summary(html)
    catalog = catalog_id or summary.get("catalog_id")

    if sold_map is None and catalog:
        sold_map = fetch_latest_sold_prices(str(catalog), timeout=timeout)

    # 每个成色附带 sold_price/sold_at（不影响在售价 price 与爬取逻辑）
    for grade, v in conditions.items():
        sv = (sold_map or {}).get(grade)
        v["sold_price"] = sv.get("sold_price") if sv else None
        v["sold_format"] = sv.get("sold_format") if sv else None
        v["sold_price_jpy"] = sv.get("sold_price_jpy") if sv else None
        v["sold_at"] = sv.get("sold_at") if sv else None

    available = [v["price"] for v in conditions.values() if v.get("price") is not None]
    min_price = min(available) if available else None

    name_ja = summary.get("name_ja", "") or ""
    name = summary.get("name", "") or ""
    return {
        "card_id": str(card_id),
        "url": url,
        "name": name,
        "name_ja": name_ja,
        "card_name": name_ja or name,
        "brand": summary.get("brand", ""),
        "product_code": summary.get("product_code", ""),
        "catalog_id": catalog,
        "image_url": summary.get("image_url", ""),
        "listing_count": summary.get("listing_count"),
        "sale_count_text": summary.get("sale_count_text", ""),
        "min_price": min_price,
        "min_price_format": fx.format_hkd(min_price),
        "conditions": conditions,
    }


def fetch_condition_prices(
    card_id: str,
    card_data: Optional[Dict] = None,
    timeout: int = 10,
    fresh: bool = False,
    catalog_id=None,
) -> Dict[str, Dict]:
    """
    获取商品每个状态的成色价格字典（含 price=当前最低在售价、sold_price=最新已售(1枚)，
    均已换算港币）。用于写库/自动更新流程请传 fresh=True 强制抓取最新。

    Args:
        card_id: 商品 numeric ID（对应 /apparels/{id}）
        card_data: 兼容旧调用（不再使用）

    Returns:
        { 等级: {"price", "format", "sold_price", "sold_format", "sold_at", "count", ...} }
    """
    detail = fetch_card_detail(card_id, timeout=timeout, catalog_id=catalog_id, fresh=fresh)
    if not detail:
        return {}
    return detail.get("conditions", {})


def condition_effective_price(v: Optional[Dict]) -> tuple:
    """
    成色有效成交价：最新已售(1枚)优先，无已售记录时退回当前在售价。
    Returns:
        (price_hkd: Optional[float], format_text: Optional[str])
    """
    if not v:
        return None, None
    if v.get("sold_price") is not None:
        p = float(v["sold_price"])
        return p, v.get("sold_format") or fx.format_hkd(p)
    if v.get("price") is not None:
        p = float(v["price"])
        return p, v.get("format") or fx.format_hkd(p)
    return None, None


def fetch_product_detail(card_id: str, timeout: int = 15) -> Optional[Dict]:
    """
    爬取商品详情并返回与旧模型兼容的数据字典（一次请求完成，价格已换算为港币）。
    主要用途：Web 爬取 / 导入 MySQL。
    """
    url = DETAIL_URL.format(id=card_id)
    html = fetch_text(url, timeout=timeout)
    if not html:
        return None

    conditions = _conditions_from_chips(_parse_condition_chips(html))
    summary = _parse_product_summary(html)

    # 基础信息（优先用 RSC 摘要，回退到页面 meta）
    title = summary.get("name_ja") or summary.get("name") or ""
    og = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    if og:
        title = og.group(1)
    desc = ""
    md = re.search(r'<meta name="description" content="([^"]*)"', html)
    if md:
        desc = md.group(1)
    img = summary.get("image_url") or ""
    if not img:
        oi = re.search(r'<meta property="og:image" content="([^"]*)"', html)
        if oi:
            img = oi.group(1)
    product_number = summary.get("product_code") or ""
    if not product_number:
        pn = re.search(r'"productNumber":\s*"([^"]+)"', html)
        if pn:
            product_number = pn.group(1)

    available = [v for v in conditions.values() if v.get("price") is not None]
    min_price = min(v["price"] for v in available) if available else None

    deal_condition = None
    if "A" in conditions and conditions["A"].get("price") is not None:
        deal_condition = "A"
    elif available:
        deal_condition = next(g for g, v in conditions.items() if v.get("price") is not None)
    deal_price = None
    deal_format = "-"
    if deal_condition and conditions.get(deal_condition):
        deal_price = conditions[deal_condition]["price"]
        deal_format = conditions[deal_condition]["format"]

    # 商品名保留完整标题（与搜索结果显示一致），仅去掉站点来源尾缀
    # （…｜スニダン / 通販・買取・相場 / | SNKRDUNK）
    clean_title = title.replace(" | SNKRDUNK", "").strip()
    clean_title = re.sub(r"｜スニダン\s*$", "", clean_title).strip()
    clean_title = re.sub(r"通販・買取・相場\s*$", "", clean_title).strip()
    card_name = clean_title

    low_title = (title or "").lower()
    card_type = "single"
    if any(k in low_title for k in ("box", "pack", "デッキ", "セット", "パック")):
        card_type = "box_pack"

    return {
        "id": str(card_id),
        "url": url,
        "title": title,
        "card_name": card_name or title,
        "brand": summary.get("brand", ""),
        "category": "",
        "min_price": min_price,
        "product_code": product_number,
        "thumbnail_url": img,
        "card_type": card_type,
        "description": desc,
        "listing_count": len(available),
        "in_stock_count": summary.get("listing_count"),
        "offer_count": "",
        "image_urls": [img] if img else [],
        "image_count": 1 if img else 0,
        "condition_prices": conditions,
        "deal_condition": deal_condition,
        "deal_price": deal_price,
        "deal_format": deal_format,
        "currency": "HKD",
        "_source": "new_site",
    }


def format_condition_summary(condition_prices: Dict[str, Dict]) -> str:
    """格式化成色价格摘要"""
    order = ["S", "A", "B", "C", "D", "PSA 10", "PSA 9", "PSA 8 or under",
             "BGS 10 BL", "BGS 10 GL", "BGS 9.5", "BGS 9 or under",
             "ARS 10+", "ARS 10", "ARS 9", "ARS 8 or under", "Other"]
    parts = []
    for grade in order:
        cp = condition_prices.get(grade, {})
        if cp.get("price") is not None:
            parts.append(f"{grade}:{fx.format_hkd(cp['price'])}")
        else:
            parts.append(f"{grade}:-")
    return " | ".join(parts)
