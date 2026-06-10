"""
Compare Utilities - 检测新增卡片和数据变更

工作流程:
  1. URL 对比: 将旧的 URL 列表与新的 sitemap 对比，发现新增/删除的卡片
  2. 数据对比: 重新爬取旧卡片的子集，比较价格、数量等关键字段的变化
  3. 输出报告: 生成结构化的变更报告（JSON/Markdown）
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from .sitemap_parser import discover_all_card_urls

# 要追踪变化的关键字段
TRACKED_FIELDS = [
    "min_price",
    "min_price_format",
    "max_price",
    "max_price_format",
    "used_min_price",
    "used_min_price_format",
    "used_listing_count",
    "listing_count",
    "offer_count",
]

# 用于标识卡片唯一性的"指纹"字段
FINGERPRINT_FIELDS = ["min_price", "used_min_price", "used_listing_count", "listing_count"]


# ====================================================================
#  URL 变化检测
# ====================================================================

def load_previous_urls(manifest_path: str) -> Set[str]:
    """加载上一次的 URL manifest"""
    if not os.path.exists(manifest_path):
        return set()
    with open(manifest_path, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_url_manifest(urls: List[str], manifest_path: str):
    """保存当前 URL 列表到 manifest 文件（含时间戳头部）"""
    os.makedirs(os.path.dirname(manifest_path) or ".", exist_ok=True)
    now = datetime.now().isoformat()
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(f"# SNKRDUNK URL Manifest\n")
        f.write(f"# Generated: {now}\n")
        f.write(f"# Total: {len(urls)}\n")
        # 写入 URL 按 ID 排序
        sorted_urls = sorted(urls, key=lambda u: int(u.rstrip("/").split("/")[-1]) if u.rstrip("/").split("/")[-1].isdigit() else u)
        for url in sorted_urls:
            f.write(url + "\n")


def detect_url_changes(current_urls: Set[str], previous_urls: Set[str]) -> Dict:
    """检测 URL 变化，返回新增和删除的 URL"""
    new_urls = current_urls - previous_urls
    removed_urls = previous_urls - current_urls

    return {
        "new": sorted(new_urls),
        "removed": sorted(removed_urls),
        "total_current": len(current_urls),
        "total_previous": len(previous_urls),
        "new_count": len(new_urls),
        "removed_count": len(removed_urls),
    }


# ====================================================================
#  数据变更检测
# ====================================================================

def load_previous_data(json_path: str) -> Dict[str, Dict]:
    """加载上一次的爬取结果，返回 {card_id: data} 的字典"""
    if not os.path.exists(json_path):
        return {}
    with open(json_path, "r", encoding="utf-8") as f:
        data_list = json.load(f)
    return {item["id"]: item for item in data_list}


def compare_card_data(old_data: Dict, new_data: Dict) -> Dict:
    """
    对比单张卡片的字段变化

    Returns:
        {
            "id": "103043",
            "card_name": "...",
            "changed_fields": {
                "min_price": {"old": 7, "new": 8},
                "used_listing_count": {"old": 17, "new": 15},
            },
            "unchanged_fields": [...],
            "is_changed": True/False
        }
    """
    changed = {}
    unchanged = []

    for field in TRACKED_FIELDS:
        old_val = old_data.get(field)
        new_val = new_data.get(field)
        # 将值转为字符串比较，避免类型差异（如 int vs str）
        if str(old_val) != str(new_val):
            changed[field] = {"old": old_val, "new": new_val}
        else:
            unchanged.append(field)

    return {
        "id": old_data.get("id", new_data.get("id")),
        "card_name": old_data.get("card_name", new_data.get("card_name", "")),
        "url": old_data.get("url", new_data.get("url", "")),
        "brand": old_data.get("brand", new_data.get("brand", "")),
        "changed_fields": changed,
        "unchanged_fields": unchanged,
        "is_changed": len(changed) > 0,
    }


def compute_fingerprint(data: Dict) -> str:
    """计算卡片数据的指纹，用于快速判断是否发生变化"""
    values = [str(data.get(f, "")) for f in FINGERPRINT_FIELDS]
    return "|".join(values)


def batch_compare(
    old_data_map: Dict[str, Dict],
    new_results: List[Dict],
) -> Dict:
    """
    批量对比新旧数据

    Args:
        old_data_map: {card_id: data} 旧数据
        new_results: 新爬取的卡片数据列表

    Returns:
        {
            "total_old": 1000,
            "total_new": 10,
            "changed_cards": [...],
            "total_changed": 5,
            "no_data_fields": {...}  # 某些字段在旧数据中缺失的统计
        }
    """
    changed_cards = []
    for item in new_results:
        cid = item.get("id", "")
        if cid in old_data_map:
            diff = compare_card_data(old_data_map[cid], item)
            if diff["is_changed"]:
                changed_cards.append(diff)

    return {
        "total_old": len(old_data_map),
        "total_new": len(new_results),
        "changed_cards": changed_cards,
        "total_changed": len(changed_cards),
    }


# ====================================================================
#  报告生成
# ====================================================================

def generate_diff_report(
    url_changes: Dict,
    data_changes: Dict,
    new_card_data: Optional[List[Dict]] = None,
    output_dir: str = "data",
) -> str:
    """
    生成变更报告的 JSON 文件

    Returns:
        报告文件路径
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "url_changes": {
            "new_count": url_changes["new_count"],
            "removed_count": url_changes["removed_count"],
            "total_current": url_changes["total_current"],
            "total_previous": url_changes["total_previous"],
            "new_urls": url_changes["new"][:100],       # 最多列出 100 条
            "removed_urls": url_changes["removed"][:100],
        },
        "data_changes": {
            "cards_scanned": data_changes["total_new"],
            "cards_changed": data_changes["total_changed"],
            "changed_cards": [
                {
                    "id": c["id"],
                    "card_name": c["card_name"][:60],
                    "url": c["url"],
                    "brand": c["brand"],
                    "changed_fields": c["changed_fields"],
                }
                for c in data_changes["changed_cards"]
            ],
        },
        "new_cards_added": len(new_card_data) if new_card_data else 0,
    }

    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "diff_report.json")

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report_path


def print_diff_summary(url_changes: Dict, data_changes: Dict):
    """在终端打印变更摘要"""
    print("\n" + "=" * 60)
    print("CHANGE DETECTION REPORT")
    print("=" * 60)

    print(f"\n[URL Changes]:")
    print(f"  Current total:  {url_changes['total_current']}")
    print(f"  Previous total: {url_changes['total_previous']}")
    print(f"  + New cards:   {url_changes['new_count']}")
    print(f"  - Removed:     {url_changes['removed_count']}")

    if url_changes["new"]:
        print(f"\n  New card URLs (first 5):")
        for url in url_changes["new"][:5]:
            print(f"    {url}")

    print(f"\n[Data Changes]:")
    print(f"  Cards re-scanned:   {data_changes['total_new']}")
    print(f"  Cards with changes: {data_changes['total_changed']}")

    if data_changes["changed_cards"]:
        print(f"\n  Changed cards (first 10):")
        for c in data_changes["changed_cards"][:10]:
            fields = ", ".join(
                f"{k}: {v['old']}→{v['new']}"
                for k, v in c["changed_fields"].items()
            )
            print(f"    [{c['id']}] {c['card_name'][:50]}")
            print(f"           {fields}")

    print("=" * 60)
