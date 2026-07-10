"""
Search API - 通过 SNKRDUNK v1 搜索 API 查找交易卡

API 端点: https://snkrdunk.com/en/v1/search?keyword=...&perPage=21&page=1&type=
交易卡数据在响应中的 streetwears 数组里。
perPage 最大 200, 无分页信息。

说明：使用内置 urllib 而非 requests，兼容 CentOS 7 旧版 OpenSSL。
"""

import concurrent.futures
import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

SEARCH_URL = "https://snkrdunk.com/en/v1/search"
MAX_PER_PAGE = 200

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
    "Accept": "application/json",
}


def _urlopen(url: str, timeout: int = 30):
    """使用 urllib 发送 GET 请求（兼容旧 OpenSSL）"""
    req = urllib.request.Request(url, headers=_HEADERS)
    return urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout)


def search_trading_cards(
    keyword: str,
    max_results: int = 50,
    per_page: int = 200,
) -> List[Dict]:
    """
    通过 API 搜索交易卡

    Args:
        keyword: 搜索关键词（多词用空格分隔，函数自动拼接为 +）
        max_results: 最多返回结果数
        per_page: 每页数量（最大 200）

    Returns:
        卡片列表
    """
    api_keyword = keyword.strip().replace(" ", "+")
    params = (
        f"keyword={urllib.request.quote(api_keyword)}"
        f"&perPage={min(per_page, MAX_PER_PAGE)}"
        f"&page=1&type="
    )
    url = f"{SEARCH_URL}?{params}"

    try:
        with _urlopen(url) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"[ERROR] 搜索 API 请求失败: {e}")
        return []

    tcg_results = data.get("streetwears", [])
    total_count = data.get("streetwearCount", len(tcg_results))

    results = tcg_results[:max_results]

    normalized = []
    for item in results:
        normalized.append({
            "id": str(item.get("id", "")),
            "card_name": item.get("name", ""),
            "min_price": item.get("minPrice"),
            "min_price_format": item.get("minPriceFormat", ""),
            "listing_count": item.get("listingCount", "0"),
            "all_listing_count": item.get("allListingCount", ""),
            "offer_count": item.get("offerCount", "0"),
            "thumbnail_url": item.get("thumbnailUrl", ""),
            "release_date": item.get("releasedAt", ""),
            "is_trading_card": item.get("isTradingCard", False),
            "product_number": item.get("productNumber", ""),
            "_source": "search_api",
        })

    return normalized


def print_search_results(results: List[Dict], keyword: str):
    """打印搜索结果摘要"""
    print(f"\n{'=' * 60}")
    print(f"搜索结果: '{keyword}' - {len(results)} 张卡片")
    print(f"{'=' * 60}")
    for i, r in enumerate(results):
        name = r.get("card_name", "")[:65]
        price = r.get("min_price", "?")
        listings = r.get("listing_count", "?")
        print(f"  [{i+1}] [{r['id']}] {name}")
        print(f"      最低价: ${price}  |  listing: {listings}")


def save_search_results(results: List[Dict], filepath: str):
    """保存搜索结果到文件"""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  搜索列表已保存: {filepath}")


# ============================================================
#  成色(Condition)价格查询
# ============================================================

# 成色等级映射：conditionID -> (等级, 名称)
CONDITION_MAP = {
    18: ("A", "A"),
    19: ("B", "B"),
    20: ("C", "C"),
    21: ("D", "D"),
    22: ("PSA 10", "PSA 10"),
    23: ("PSA 9", "PSA 9"),
    24: ("PSA 8 or under", "PSA 8 or under"),
    25: ("BGS 10 BL", "BGS 10 BL"),
    26: ("BGS 10 GL", "BGS 10 GL"),
}

CONDITION_IDS = sorted(CONDITION_MAP.keys())  # [18, 19, ..., 26]

USED_LISTINGS_URL = "https://snkrdunk.com/en/v1/products/{product_id}/used-listings"


def _get_product_id(card_id: str, card_data: Optional[Dict] = None) -> str:
    """
    从卡片 ID 或数据中获取产品的完整 ID（如 SW---418755）。
    
    搜索 API 返回的 cardNumber 或 productNumber 已经是完整格式，
    没有的话就拼接 SW---{card_id}。
    """
    if card_data:
        pn = card_data.get("product_number") or card_data.get("productNumber", "")
        if pn and pn.startswith("SW"):
            return pn
    if card_id and not card_id.startswith("SW"):
        return f"SW---{card_id}"
    return card_id


def fetch_condition_prices(
    card_id: str,
    card_data: Optional[Dict] = None,
    timeout: int = 10,
) -> Dict[str, Dict]:
    """
    获取卡片所有成色（A~I）的最低价格（并行请求，大幅加快速度）

    Args:
        card_id: 卡片数字 ID
        card_data: 卡片数据（可选，含 product_number 时可避免拼接）
        timeout: 每个请求超时时间

    Returns:
        { "A": {"price": 123.45, "format": "¥12,345", "count": 3, "error": None}, ... }
    """
    product_id = _get_product_id(card_id, card_data)
    if not product_id or "---" not in str(product_id):
        product_id = f"SW---{card_id}"

    base_params = "perPage=1&page=1&sortType=latest&isOnlyOnSale=false"
    urls = []
    for cid in CONDITION_IDS:
        grade, _ = CONDITION_MAP[cid]
        url = f"{USED_LISTINGS_URL.format(product_id=product_id)}?{base_params}&conditionID={cid}"
        urls.append((cid, grade, url))

    def _fetch_one(cid, grade, url):
        """
        抓取单个成色价格。
        逐步增大 perPage 直到找到 isSold=true 的记录，取其价格作为成色价格。
        """
        try:
            # 逐步增大翻页数，直到找到已售记录
            page_sizes = [1, 5, 10, 20]
            fallback_listings = []
            total_count = 0

            for ps in page_sizes:
                page_url = re.sub(r"perPage=\d+", f"perPage={ps}", url)
                try:
                    with _urlopen(page_url, timeout=timeout) as resp:
                        data = json.loads(resp.read().decode("utf-8", errors="replace"))
                except urllib.error.HTTPError as e:
                    body = ""
                    try:
                        body = e.read().decode("utf-8", errors="replace")[:100]
                    except Exception:
                        pass
                    return grade, {"price": None, "format": "-", "count": 0, "error": f"HTTP {e.code}"}
                except json.JSONDecodeError as e:
                    return grade, {"price": None, "format": "-", "count": 0, "error": f"JSON: {e}"}
                except Exception as e:
                    return grade, {"price": None, "format": "-", "count": 0, "error": str(e)[:80]}

                # 解析 listings
                listings = []
                if isinstance(data, dict):
                    listings = data.get("listings", data.get("usedListings", data.get("data", [])))
                    if not isinstance(listings, list):
                        listings = []
                    total_count = data.get("listingCount", data.get("totalCount", len(listings)))
                    if not total_count:
                        total_count = len(listings)
                elif isinstance(data, list):
                    listings = data
                    total_count = len(listings)
                else:
                    return grade, {"price": None, "format": "-", "count": 0, "error": "未知格式"}

                fallback_listings.extend(listings)

                # 检查是否找到已售记录
                for item in listings:
                    if item.get("isSold") is True:
                        p = item.get("priceAmount") or item.get("price") or item.get("minPrice")
                        if p is not None:
                            try:
                                pv = float(p)
                                price_format = item.get("priceFormat", item.get("minPriceFormat", ""))
                                if not price_format:
                                    price_format = f"${pv:.2f}"
                                return grade, {
                                    "price": round(pv, 2),
                                    "format": price_format,
                                    "count": int(total_count) if total_count else 1,
                                    "error": None,
                                }
                            except (ValueError, TypeError):
                                pass

                # 如果当前页返回数量小于 perPage，说明没有更多数据了
                if len(listings) < ps:
                    break

            # 没有找到已售记录，回退到所有 listings 的最低价格
            min_price = None
            min_format = ""
            for item in fallback_listings:
                p = item.get("priceAmount") or item.get("price") or item.get("minPrice")
                if p is not None:
                    try:
                        pv = float(p)
                        if min_price is None or pv < min_price:
                            min_price = pv
                            min_format = item.get("priceFormat", item.get("minPriceFormat", ""))
                    except (ValueError, TypeError):
                        pass

            return grade, {
                "price": round(min_price, 2) if min_price is not None else None,
                "format": min_format if min_format else (f"${min_price:.2f}" if min_price is not None else "-"),
                "count": int(total_count) if total_count else 0,
                "error": None,
            }

        except Exception as e:
            return grade, {"price": None, "format": "-", "count": 0, "error": str(e)[:80]}

    # 并行请求（最多 9 个线程）
    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as executor:
        futures = {executor.submit(_fetch_one, cid, grade, url): (cid, grade)
                   for cid, grade, url in urls}
        for future in concurrent.futures.as_completed(futures, timeout=timeout + 5):
            try:
                grade, data = future.result()
                result[grade] = data
            except Exception as e:
                # 超时等异常
                cid, grade = futures[future]
                result[grade] = {"price": None, "format": "-", "count": 0, "error": f"并行请求超时: {e}"[:80]}

    # 确保所有等级都有结果
    for _, grade in CONDITION_MAP.values():
        if grade not in result:
            result[grade] = {"price": None, "format": "-", "count": 0, "error": "无响应"}

    return result


def format_condition_summary(condition_prices: Dict[str, Dict]) -> str:
    """格式化成色价格摘要"""
    parts = []
    for grade in ["A", "B", "C", "D", "PSA 10", "PSA 9", "PSA 8 or under", "BGS 10 BL", "BGS 10 GL"]:
        cp = condition_prices.get(grade, {})
        if cp.get("price") is not None:
            parts.append(f"{grade}:${cp['price']:.2f}")
        else:
            parts.append(f"{grade}:-")
    return " | ".join(parts)
