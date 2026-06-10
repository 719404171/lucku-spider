"""
Condition Price Scraper - 获取卡片不同状态(Condition)下的最新价格

SNKRDUNK 的二手 listing 数据是客户端动态渲染的 (Vue.js), 
无法从静态 HTML 中直接获取每个 listing 的 URL。

但我们能从卡片页面的 :summary 属性中获取以下定价数据:
  - min_price / max_price: 整体价格范围
  - used_min_price: 二手最低价
  - used_listing_count: 二手 listing 数量
  
对于已知的单个 listing URL, 可以爬取条件级价格。
"""

import csv
import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .card_scraper import CardScraper

# 条件等级映射
CONDITION_LABELS = {
    "N": "New (新品)",
    "A": "A - Mint (完美品)",
    "B": "B - Excellent (优良品)",
    "C": "C - Good (良好品)",
    "D": "D - Fair (一般品)",
}


def generate_price_report(
    card_data: List[Dict],
    listing_data: Optional[List[Dict]] = None,
    output_dir: str = "data",
) -> str:
    """
    从现有卡片数据生成价格报告

    Args:
        card_data: 卡片数据列表（来自 trading_cards.json）
        listing_data: 可选的 listing 级数据（含 condition + price）
        output_dir: 输出目录

    Returns:
        报告文件路径
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "total_cards": len(card_data),
        "cards_with_listings": 0,
        "cards_without_listings": 0,
        "price_summary": {
            "overall_min_price": None,
            "overall_max_price": None,
            "overall_avg_used_min_price": None,
        },
        "condition_breakdown": {},  # condition -> count, avg_price, min, max
        "sample_listings": [],
        "limitations": [
            "各 Condition (A/B/C/D) 的逐级价格需要访问单个 listing 页面",
            "单个 listing URL 需通过浏览器开发者工具从 /used 页面获取",
            "本报告基于卡片页面 :summary 中的聚合数据生成",
        ],
    }

    prices = []
    used_prices = []
    cards_with_listings = 0

    for card in card_data:
        min_p = card.get("min_price")
        used_min = card.get("used_min_price")
        used_count = card.get("used_listing_count") or 0

        if isinstance(min_p, (int, float)):
            prices.append(min_p)

        if used_count > 0:
            cards_with_listings += 1

        # used_min_price 可能是字符串 ("US $7") 或数字
        if isinstance(used_min, (int, float)):
            used_prices.append(used_min)
        elif isinstance(used_min, str):
            # 尝试从字符串提取数字
            match = re.search(r"[\d,]+(?:\.\d+)?", used_min)
            if match:
                used_prices.append(float(match.group().replace(",", "")))

    report["cards_with_listings"] = cards_with_listings
    report["cards_without_listings"] = len(card_data) - cards_with_listings

    if prices:
        report["price_summary"]["overall_min_price"] = min(prices)
        report["price_summary"]["overall_max_price"] = max(prices)

    if used_prices:
        report["price_summary"]["overall_avg_used_min_price"] = round(
            sum(used_prices) / len(used_prices), 2
        )

    # 如果有 listing 级数据，按 condition 分组
    if listing_data:
        by_condition: Dict[str, List] = {}
        for item in listing_data:
            cond = item.get("condition", "Unknown")
            if cond not in by_condition:
                by_condition[cond] = []
            by_condition[cond].append(item)

        for cond in sorted(by_condition.keys()):
            items = by_condition[cond]
            amounts = [
                i["price_amount"]
                for i in items
                if i.get("price_amount") is not None
            ]
            label = CONDITION_LABELS.get(cond, f"Condition {cond}")
            breakdown = {
                "condition": cond,
                "label": label,
                "count": len(items),
                "min_price": min(amounts) if amounts else None,
                "max_price": max(amounts) if amounts else None,
                "avg_price": round(sum(amounts) / len(amounts), 2) if amounts else None,
            }
            report["condition_breakdown"][cond] = breakdown

        # 样品 listing
        report["sample_listings"] = [
            {
                "uid": l.get("listing_id", ""),
                "condition": l.get("condition", ""),
                "price": l.get("price", ""),
                "price_amount": l.get("price_amount"),
            }
            for l in listing_data[:20]
        ]

    # 保存报告
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "price_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report_path


def print_price_summary(card_data: List[Dict], listing_data: Optional[List[Dict]] = None):
    """打印价格汇总"""
    print("\n" + "=" * 60)
    print("PRICE REPORT - 卡片价格汇总")
    print("=" * 60)

    total = len(card_data)
    with_listings = sum(
        1 for c in card_data if (c.get("used_listing_count") or 0) > 0
    )
    with_min_price = sum(1 for c in card_data if c.get("min_price") is not None)
    with_used_price = sum(1 for c in card_data if c.get("used_min_price"))

    print(f"\n[数据概览]:")
    print(f"  卡片总数: {total}")
    print(f"  有最低价: {with_min_price}")
    print(f"  有二手 listing: {with_listings} ({with_listings/total*100:.1f}%)")
    print(f"  有二手最低价: {with_used_price}")

    # 价格统计
    prices = [
        c["min_price"] for c in card_data
        if isinstance(c.get("min_price"), (int, float))
    ]
    if prices:
        print(f"\n[价格统计] (所有卡片):")
        print(f"  平均价: ${sum(prices)/len(prices):.2f}")
        print(f"  最低: ${min(prices)}")
        print(f"  最高: ${max(prices)}")

    used_prices = []
    for c in card_data:
        up = c.get("used_min_price")
        if isinstance(up, (int, float)):
            used_prices.append(up)
        elif isinstance(up, str):
            m = re.search(r"[\d,]+(?:\.\d+)?", up)
            if m:
                used_prices.append(float(m.group().replace(",", "")))

    if used_prices:
        print(f"\n[二手价格统计]:")
        print(f"  平均二手最低价: ${sum(used_prices)/len(used_prices):.2f}")
        print(f"  最低: ${min(used_prices)}")
        print(f"  最高: ${max(used_prices)}")

    # Condition breakdown
    if listing_data:
        by_cond: Dict[str, list] = {}
        for item in listing_data:
            c = item.get("condition", "?")
            amt = item.get("price_amount")
            if amt is not None:
                by_cond.setdefault(c, []).append(amt)

        if by_cond:
            print(f"\n[按 Condition 分类价格]:")
            for cond in sorted(by_cond.keys()):
                vals = by_cond[cond]
                label = CONDITION_LABELS.get(cond, f"Condition {cond}")
                print(f"  {label}:")
                print(f"    数量: {len(vals)}")
                print(f"    均价: ${sum(vals)/len(vals):.2f}")
                print(f"    范围: ${min(vals)} ~ ${max(vals)}")

    print("=" * 60)


def scrape_known_listings(
    scraper: CardScraper,
    listing_uids: List[str],
    delay: float = 1.0,
) -> List[Dict]:
    """
    爬取已知 listing URL 的条件级价格数据

    Args:
        scraper: CardScraper 实例
        listing_uids: listing UID 列表
        delay: 请求延迟

    Returns:
        listing 数据列表
    """
    results = []
    total = len(listing_uids)
    for i, uid in enumerate(listing_uids):
        url = f"https://snkrdunk.com/en/trading-cards/used/listings/{uid}"
        print(f"\n[{i + 1}/{total}] ", end="")
        data = scraper.scrape_listing(url)
        if data:
            results.append(data)
        time.sleep(delay)
    return results


def extract_listing_uids_from_file(filepath: str) -> List[str]:
    """
    从文本文件中读取 listing UID（每行一个 UID 或 URL）。
    文件格式示例:
        01H2K2ARP08CD234BX03N4ETYN
        https://snkrdunk.com/en/trading-cards/used/listings/01H2K2ARP08CD234BX03N4ETYN
    """
    if not os.path.exists(filepath):
        return []

    uids = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # 从完整 URL 中提取 UID
            match = re.search(r"/listings/([\w-]+)", line)
            if match:
                uids.append(match.group(1))
            elif re.match(r"^[\w-]{20,}$", line):
                uids.append(line)
    return uids
