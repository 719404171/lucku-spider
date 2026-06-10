"""
Sitemap Parser - 从 SNKRDUNK sitemap 中获取所有交易卡 URL
"""

import gzip
import io
import json
import re
import time
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://snkrdunk.com"
SITEMAP_INDEX_URL = "https://snkrdunk.com/en/sitemap/sitemap-index-en-product-trading-card-single.xml"


def fetch_with_gzip(url: str) -> Optional[str]:
    """
    获取 URL 内容，自动处理 gzip 解压。
    某些 sitemap 使用 Content-Type: application/x-gzip，需要手动解压。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }
    try:
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        # 如果是 gzip 格式，手动解压
        if "gzip" in content_type or url.endswith(".gz"):
            try:
                decompressed = gzip.decompress(resp.content)
                return decompressed.decode("utf-8")
            except Exception:
                # 如果解压失败，尝试直接使用 text
                return resp.text
        else:
            return resp.text
    except requests.RequestException as e:
        print(f"[ERROR] Failed to fetch {url}: {e}")
        return None


def parse_sitemap_index(xml_content: str) -> List[str]:
    """解析 sitemap index，返回子 sitemap URL 列表"""
    urls = []
    try:
        soup = BeautifulSoup(xml_content, "lxml-xml")
        for sitemap_tag in soup.find_all("sitemap"):
            loc = sitemap_tag.find("loc")
            if loc and loc.text:
                urls.append(loc.text.strip())
    except Exception as e:
        print(f"[ERROR] Failed to parse sitemap index: {e}")
    return urls


def parse_sitemap_urls(xml_content: str) -> List[str]:
    """解析 sitemap 文件，返回所有 URL 列表"""
    urls = []
    try:
        soup = BeautifulSoup(xml_content, "lxml-xml")
        for url_tag in soup.find_all("url"):
            loc = url_tag.find("loc")
            if loc and loc.text:
                urls.append(loc.text.strip())
    except Exception as e:
        print(f"[ERROR] Failed to parse sitemap: {e}")
    return urls


def get_sitemap_urls_from_index() -> List[str]:
    """获取 sitemap index 中所有子 sitemap 的 URL"""
    print("[INFO] Fetching sitemap index...")
    xml_content = fetch_with_gzip(SITEMAP_INDEX_URL)
    if not xml_content:
        print("[ERROR] Failed to fetch sitemap index")
        return []

    sitemap_urls = parse_sitemap_index(xml_content)
    print(f"[INFO] Found {len(sitemap_urls)} single card sitemaps")
    return sitemap_urls


def get_all_urls_from_sitemaps(sitemap_urls: List[str], delay: float = 0.5) -> List[str]:
    """从所有 sitemap 中提取所有 URL"""
    all_urls: List[str] = []
    for i, sitemap_url in enumerate(sitemap_urls):
        print(f"[INFO] Fetching sitemap {i + 1}/{len(sitemap_urls)}...")
        xml_content = fetch_with_gzip(sitemap_url)
        if xml_content:
            urls = parse_sitemap_urls(xml_content)
            all_urls.extend(urls)
            print(f"[INFO]   Found {len(urls)} URLs (total: {len(all_urls)})")
        else:
            print(f"[WARN]   Failed to fetch sitemap {sitemap_url}")
        time.sleep(delay)

    return all_urls


def filter_trading_card_urls(urls: List[str]) -> List[str]:
    """过滤出交易卡 URL（排除非卡片页面）"""
    pattern = re.compile(r"^https://snkrdunk\.com/en/trading-cards/\d+$")
    return [url for url in urls if pattern.match(url)]


def discover_all_card_urls(delay: float = 0.5) -> List[str]:
    """
    完整流程：获取 sitemap index -> 获取所有 sitemap -> 提取所有卡片 URL
    
    Args:
        delay: 请求之间的延迟（秒）
    
    Returns:
        所有交易卡页面的 URL 列表
    """
    sitemap_urls = get_sitemap_urls_from_index()
    if not sitemap_urls:
        return []

    all_urls = get_all_urls_from_sitemaps(sitemap_urls, delay)
    print(f"[INFO] Total URLs found from sitemaps: {len(all_urls)}")

    card_urls = filter_trading_card_urls(all_urls)
    print(f"[INFO] Trading card URLs after filtering: {len(card_urls)}")

    return card_urls


if __name__ == "__main__":
    urls = discover_all_card_urls()
    print(f"\nSample card URLs:")
    for url in urls[:10]:
        print(f"  {url}")
