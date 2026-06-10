"""
Search API - 通过 SNKRDUNK v1 搜索 API 查找交易卡

API 端点: https://snkrdunk.com/en/v1/search?keyword=...&perPage=21&page=1&type=
交易卡数据在响应中的 streetwears 数组里。
perPage 最大 200, 无分页信息。

说明：使用内置 urllib 而非 requests，兼容 CentOS 7 旧版 OpenSSL。
"""

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
