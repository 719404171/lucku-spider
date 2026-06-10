"""
Utility functions for the scraper
"""

import json
import os
from typing import Dict, List, Optional


def load_urls_from_file(filepath: str) -> List[str]:
    """从文件加载 URL 列表（每行一个 URL）"""
    with open(filepath, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_urls_to_file(urls: List[str], filepath: str):
    """保存 URL 列表到文件"""
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for url in urls:
            f.write(url + "\n")
    print(f"[INFO] Saved {len(urls)} URLs to {filepath}")


def print_stats(results: List[Dict]):
    """打印爬取结果的统计信息"""
    if not results:
        print("[INFO] No data to analyze")
        return

    brands = {}
    categories = {}
    card_types = {"single": 0, "box_pack": 0}
    total_used_listings = 0
    cards_with_used_listings = 0
    cards_with_listing_price = 0

    for item in results:
        b = item.get("brand", "Unknown")
        brands[b] = brands.get(b, 0) + 1

        c = item.get("category", "Unknown")
        categories[c] = categories.get(c, 0) + 1

        ct = item.get("card_type", "single")
        card_types[ct] = card_types.get(ct, 0) + 1

        used_count = item.get("used_listing_count") or 0
        if used_count:
            total_used_listings += used_count
            cards_with_used_listings += 1

        if item.get("used_min_price"):
            cards_with_listing_price += 1

    print("\n" + "=" * 50)
    print("SCRAPING STATISTICS")
    print("=" * 50)
    print(f"Total cards scraped: {len(results)}")
    print(f"\nCard types:")
    for ct, count in sorted(card_types.items()):
        print(f"  {ct}: {count}")

    print(f"\nUsed Listings:")
    print(f"  Cards with used listings: {cards_with_used_listings}")
    print(f"  Total used listings: {total_used_listings}")
    print(f"  Cards with listing price: {cards_with_listing_price}")

    print(f"\nTop 10 brands:")
    for brand, count in sorted(brands.items(), key=lambda x: -x[1])[:10]:
        print(f"  {brand}: {count}")

    print(f"\nTop 10 categories:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1])[:10]:
        print(f"  {cat}: {count}")
    print("=" * 50)
