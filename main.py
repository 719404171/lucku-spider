#!/usr/bin/env python3
"""
SNKRDUNK Trading Card Scraper

从 snkrdunk.com/en 爬取所有交易卡数据
"""

import argparse
import importlib
import json
import os
import random
import sys
import time

# 模块级导入，所有函数共享
from scraper.sitemap_parser import discover_all_card_urls
from scraper.card_scraper import CardScraper
from scraper.utils import load_urls_from_file, save_urls_to_file, print_stats
from scraper.compare_utils import (
    detect_url_changes,
    load_previous_urls,
    save_url_manifest,
    load_previous_data,
    batch_compare,
    generate_diff_report,
    print_diff_summary,
)
from scraper.condition_prices import (
    generate_price_report,
    print_price_summary,
    scrape_known_listings,
    extract_listing_uids_from_file,
)
from scraper.search_api import (
    search_trading_cards,
    print_search_results,
    save_search_results,
    fetch_product_detail,
)


def get_default_paths(output_dir: str):
    """生成默认的文件路径"""
    os.makedirs(output_dir, exist_ok=True)
    return {
        "urls": os.path.join(output_dir, "urls_cache.txt"),
        "urls_manifest": os.path.join(output_dir, "urls_manifest.txt"),
        "checkpoint": os.path.join(output_dir, "checkpoint.txt"),
    }


def main():
    parser = argparse.ArgumentParser(
        description="SNKRDUNK Trading Card Scraper - 爬取 snkrdunk.com 交易卡数据"
    )

    mode_group = parser.add_argument_group("运行模式（请选择其一）")
    mode_group.add_argument("--test", action="store_true", help="测试模式：仅爬取少量卡片验证功能")
    mode_group.add_argument("--full", action="store_true", help="完整爬取：通过 sitemap 发现并爬取所有卡片")
    mode_group.add_argument("--resume", nargs="?", const="auto", default=None, metavar="URLS_FILE",
                            help="恢复模式：从上次中断处继续")
    mode_group.add_argument("--check-updates", action="store_true",
                            help="检查更新：对比 sitemap 发现新增/删除的卡片（不爬取数据）")
    mode_group.add_argument("--diff", action="store_true",
                            help="差异检测：对比 URL + 重新采样已有卡片数据检测变化")
    mode_group.add_argument("--update", action="store_true",
                            help="增量更新：爬取新增卡片 + 检测已有卡片数据变化")
    mode_group.add_argument("--prices", action="store_true",
                            help="价格报告：从已有数据生成不同 Condition 下的价格汇总")
    mode_group.add_argument("--search", type=str, default=None, metavar="KEYWORD",
                            help="搜索模式：按关键词搜索卡片，自动从最新卡片开始扫描。"
                                 "例: --search sv8 或 --search 'pikachu vmax'")

    parser.add_argument("--max", type=int, default=None, metavar="N", help="最大爬取卡片数量")
    parser.add_argument("--delay", type=float, default=1.5, metavar="SECONDS",
                        help="请求之间的延迟（秒），默认 1.5")
    parser.add_argument("--output", type=str, default="data", metavar="DIR", help="输出目录，默认 'data'")
    parser.add_argument("--format", type=str, default="json", choices=["json", "csv", "both"],
                        help="输出格式：json / csv / both，默认 json")
    parser.add_argument("--save-urls", action="store_true", help="保存发现的 URL 列表到文件")
    parser.add_argument("--save-interval", type=int, default=0, metavar="N",
                        help="每爬取 N 张自动保存中间结果（默认仅结束时保存）")
    parser.add_argument("--sample", type=int, default=20, metavar="N",
                        help="--diff/--update 时重新采样的卡片数量，默认 20")
    parser.add_argument("--listings-file", type=str, default=None, metavar="FILE",
                        help="--prices 时指定 listing UID 文件（每行一个 UID），从中爬取条件级价格")
    parser.add_argument("--keyword", "--kw", action="append", default=[], metavar="KEYWORD",
                        dest="keywords",
                        help="关键词过滤，卡片名称必须包含该词（可多次使用，AND 逻辑）。"
                             "例: --keyword sv8 --keyword pikachu --keyword 136")
    parser.add_argument("--max-matches", type=int, default=50, metavar="N",
                        help="--search 模式最多匹配 N 张卡片后停止，默认 50")
    parser.add_argument("--scan-limit", type=int, default=None, metavar="N",
                        help="--search 模式最多扫描 N 张卡片后停止，默认不限")

    args = parser.parse_args()

    active_modes = [m for m in ["test", "full", "resume", "check_updates", "diff", "update", "prices", "search"] if getattr(args, m)]
    if not active_modes:
        parser.print_help()
        print("\n请指定运行模式：--test / --full / --resume / --check-updates / --diff / --update / --prices / --search")
        sys.exit(1)

    # snkrdunk.com/en 旧站已下线：sitemap 批量发现模式不再可用，引导改用 --search / Web UI
    if args.full or args.update or args.check_updates:
        print("=" * 60)
        print("[提示] snkrdunk.com/en 旧站已下线，sitemap 批量发现")
        print("      (--full / --update / --check-updates) 已不再可用。")
        print("请改用以下方式：")
        print("  1. Web UI:  http://127.0.0.1:5000  → 「搜索」分页搜索并爬取")
        print("  2. CLI:     python main.py --search '关键词'  (枚数固定为 1 枚)")
        print("=" * 60)
        sys.exit(0)

    paths = get_default_paths(args.output)
    scraper = CardScraper(delay=args.delay, output_dir=args.output)

    if args.test or args.full or args.resume:
        _run_scrape_mode(args, paths, scraper)
    elif args.check_updates:
        _run_check_updates(args, paths)
    elif args.diff:
        _run_diff(args, paths, scraper)
    elif args.update:
        _run_update(args, paths, scraper)
    elif args.prices:
        _run_prices(args, paths, scraper)
    elif args.search:
        _run_search_mode(args, paths, scraper)


# ====================================================================
#  各模式实现
# ====================================================================

def _run_scrape_mode(args, paths, scraper):
    """原有的 test / full / resume 逻辑"""
    card_urls = []

    if args.resume:
        urls_file = paths["urls"] if args.resume == "auto" else args.resume
        if not os.path.exists(urls_file):
            print(f"[ERROR] 未找到 URL 文件: {urls_file}")
            sys.exit(1)
        card_urls = load_urls_from_file(urls_file)
        print(f"[INFO] 从文件加载了 {len(card_urls)} 个 URL")

    elif args.full or args.test:
        print("=" * 60)
        print("Phase 1: 从 sitemap 发现交易卡 URL")
        print("=" * 60)
        card_urls = discover_all_card_urls(delay=0.5)
        if not card_urls:
            print("[ERROR] 未发现任何卡片 URL")
            sys.exit(1)

        save_url_manifest(card_urls, paths["urls_manifest"])
        if args.save_urls or args.full:
            save_urls_to_file(card_urls, paths["urls"])

        if args.test:
            card_urls = card_urls[:5]
            print(f"\n[TEST MODE] 仅爬取前 {len(card_urls)} 张卡片")

    print("\n" + "=" * 60)
    print("Phase 2: 爬取卡片详情数据")
    print(f"  Checkpoint: {paths['checkpoint']}")
    if args.keywords:
        print(f"  关键词过滤: {' & '.join(args.keywords)}")
    if args.save_interval > 0:
        print(f"  自动保存: 每 {args.save_interval} 张")
    print("=" * 60)

    start = time.time()
    results = scraper.scrape_cards(
        card_urls,
        max_cards=args.max,
        checkpoint_file=paths["checkpoint"],
        save_interval=args.save_interval,
        keywords=args.keywords if args.keywords else None,
    )
    elapsed = time.time() - start

    if results:
        print("\n" + "=" * 60)
        print("Phase 3: 保存结果")
        print("=" * 60)
        if args.format in ("json", "both"):
            scraper.save_results(results, "trading_cards.json")
        if args.format in ("csv", "both"):
            scraper.save_csv(results, "trading_cards.csv")
        print_stats(results)
        print(f"\nTotal time: {elapsed:.1f}s")
    else:
        print("[INFO] 本次没有新爬取的卡片数据")

    _show_resume_hint(paths)


def _run_check_updates(args, paths):
    """--check-updates: 仅对比 URL 列表"""
    print("=" * 60)
    print("检查更新: 从 sitemap 发现新卡片")
    print("=" * 60)

    previous_urls = load_previous_urls(paths["urls_manifest"])
    if not previous_urls:
        print("[INFO] 没有找到上一次的 URL manifest。请先运行 --full 完成首次爬取。")
        print(f"[HINT] 查找路径: {paths['urls_manifest']}")
        return

    print(f"上次记录: {len(previous_urls)} 张卡片")
    print("\n正在获取最新 sitemap...")
    current_list = discover_all_card_urls(delay=0.3)
    current_urls = set(current_list)
    print(f"当前 sitemap: {len(current_urls)} 张卡片")

    changes = detect_url_changes(current_urls, previous_urls)

    print(f"\n{'=' * 60}")
    print(f"CHANGE REPORT")
    print(f"{'=' * 60}")
    print(f"  之前: {changes['total_previous']}")
    print(f"  现在: {changes['total_current']}")
    print(f"  + 新增: {changes['new_count']}")
    print(f"  - 删除: {changes['removed_count']}")

    if changes["new"]:
        print(f"\n  新增卡片（最多 10 张）:")
        for url in changes["new"][:10]:
            card_id = url.rstrip("/").split("/")[-1]
            print(f"    [{card_id}] {url}")

    if changes["removed"]:
        print(f"\n  已删除卡片（最多 10 张）:")
        for url in changes["removed"][:10]:
            card_id = url.rstrip("/").split("/")[-1]
            print(f"    [{card_id}] {url}")

    report_path = generate_diff_report(
        changes,
        {"total_old": len(previous_urls), "total_new": 0, "changed_cards": [], "total_changed": 0},
        output_dir=args.output,
    )
    print(f"\n  报告已保存: {report_path}")

    if changes["new_count"] > 0:
        print(f"\n提示: 如需爬取新增卡片，运行: python main.py --update")
    print()


def _run_diff(args, paths, scraper):
    """--diff: URL 对比 + 数据采样对比"""
    print("=" * 60)
    print("差异检测: URL 对比 + 数据采样对比")
    print("=" * 60)

    previous_urls = load_previous_urls(paths["urls_manifest"])
    if not previous_urls:
        print("[ERROR] 没有上一次的 URL manifest。请先运行 --full。")
        return

    print("\n[1/3] 对比 sitemap 发现新增/删除...")
    current_list = discover_all_card_urls(delay=0.3)
    current_urls = set(current_list)
    url_changes = detect_url_changes(current_urls, previous_urls)
    print(f"  新增: {url_changes['new_count']}  |  删除: {url_changes['removed_count']}")

    print("\n[2/3] 加载已有爬取数据...")
    old_data_path = os.path.join(args.output, "trading_cards.json")
    old_data = load_previous_data(old_data_path)
    print(f"  加载了 {len(old_data)} 张卡片记录")

    print(f"\n[3/3] 重新采样 {args.sample} 张卡片检测数据变化...")
    sample_ids = random.sample(list(old_data.keys()), min(args.sample, len(old_data)))
    sample_urls = [f"https://snkrdunk.com/en/trading-cards/{cid}" for cid in sample_ids]
    new_results = scraper.scrape_cards(sample_urls)
    data_changes = batch_compare(old_data, new_results)

    print_diff_summary(url_changes, data_changes)
    report_path = generate_diff_report(url_changes, data_changes, output_dir=args.output)
    print(f"  详细报告: {report_path}")

    if url_changes["new_count"] > 0:
        print(f"\n提示: 如需爬取新增卡片: python main.py --update")
    print()


def _run_update(args, paths, scraper):
    """--update: 增量更新 = 爬取新增卡片 + 采样检测变化"""
    print("=" * 60)
    print("增量更新: 爬取新增卡片 + 检测已有卡片变化")
    print("=" * 60)

    previous_urls = load_previous_urls(paths["urls_manifest"])
    old_data_path = os.path.join(args.output, "trading_cards.json")

    print("\n[1/4] 获取最新 sitemap...")
    current_list = discover_all_card_urls(delay=0.3)
    current_urls = set(current_list)
    url_changes = detect_url_changes(current_urls, previous_urls)
    print(f"  之前: {url_changes['total_previous']}  ->  现在: {url_changes['total_current']}")
    print(f"  新增: {url_changes['new_count']}  |  删除: {url_changes['removed_count']}")

    new_card_data = []
    if url_changes["new"]:
        print(f"\n[2/4] 爬取 {len(url_changes['new'])} 张新增卡片...")
        new_card_data = scraper.scrape_cards(
            url_changes["new"],
            checkpoint_file=paths["checkpoint"],
            save_interval=args.save_interval,
        )
        print(f"  新增完成: {len(new_card_data)} 张")
    else:
        print("\n[2/4] 无新增卡片，跳过")

    data_changes = {"total_old": 0, "total_new": 0, "changed_cards": [], "total_changed": 0}
    old_data = load_previous_data(old_data_path) if os.path.exists(old_data_path) else {}

    if old_data and args.sample > 0:
        print(f"\n[3/4] 采样 {args.sample} 张已有卡片检测数据变化...")
        sample_size = min(args.sample, len(old_data))
        sample_ids = random.sample(list(old_data.keys()), sample_size)
        sample_urls = [f"https://snkrdunk.com/en/trading-cards/{cid}" for cid in sample_ids]
        new_results = scraper.scrape_cards(sample_urls)
        data_changes = batch_compare(old_data, new_results)
        print(f"  采样 {sample_size} 张，其中 {data_changes['total_changed']} 张数据有变化")
    else:
        print(f"\n[3/4] 跳过数据变化检测")

    print(f"\n[4/4] 保存结果...")
    if new_card_data or data_changes["changed_cards"]:
        all_cards = dict(old_data)
        for nd in new_card_data:
            all_cards[nd["id"]] = nd
        updated_list = list(all_cards.values())
        scraper.save_results(updated_list, "trading_cards.json")
        scraper.save_csv(updated_list, "trading_cards.csv")
        print(f"  合并后总计: {len(updated_list)} 张卡片")

    save_url_manifest(current_list, paths["urls_manifest"])
    save_urls_to_file(current_list, paths["urls"])
    print(f"  URL manifest 已更新")

    print_diff_summary(url_changes, data_changes)
    report_path = generate_diff_report(url_changes, data_changes, new_card_data, args.output)
    print(f"  详细报告: {report_path}")
    print()


def _run_prices(args, paths, scraper):
    """--prices: 生成卡片不同 Condition 下的价格报告"""
    data_path = os.path.join(args.output, "trading_cards.json")
    if not os.path.exists(data_path):
        print(f"[ERROR] 未找到卡片数据文件: {data_path}")
        print("[HINT] 请先运行 python main.py --test 或 --full 爬取数据")
        return

    print("=" * 60)
    print("Price Report - 卡片条件价格汇总")
    print("=" * 60)

    # 加载已有数据
    print("\n[1/3] 加载已有卡片数据...")
    with open(data_path, "r", encoding="utf-8") as f:
        card_data = json.load(f)
    print(f"  加载了 {len(card_data)} 张卡片")

    # 如果提供了 listing UID 文件，爬取条件级价格
    listing_data = None
    if args.listings_file:
        uids = extract_listing_uids_from_file(args.listings_file)
        if uids:
            print(f"\n[2/3] 从文件加载了 {len(uids)} 个 listing UID，正在爬取...")
            listing_data = scrape_known_listings(scraper, uids, delay=args.delay)
            # 保存 listing 数据
            listing_path = os.path.join(args.output, "listing_prices.json")
            with open(listing_path, "w", encoding="utf-8") as f:
                json.dump(listing_data, f, ensure_ascii=False, indent=2)
            print(f"  Listing 数据已保存: {listing_path}")
        else:
            print(f"\n[2/3] 文件 {args.listings_file} 中未找到有效的 listing UID")
    else:
        print(f"\n[2/3] 未提供 listing UID 文件，仅生成聚合价格报告")
        print(f"  [HINT] 使用 --listings-file 指定 listing UID 文件获取条件级价格")
        print(f"  [HINT] 文件每行一个 UID，可从浏览器 /used 页面获取")

    # 生成报告
    print(f"\n[3/3] 生成价格报告...")
    print_price_summary(card_data, listing_data)
    report_path = generate_price_report(card_data, listing_data, args.output)
    print(f"\n  报告已保存: {report_path}")

    if not args.listings_file:
        print(f"\n[HINT] 如需获取 Condition (A/B/C/D) 级价格:")
        print(f"  1. 浏览器打开 https://snkrdunk.com/en/trading-cards/{{card_id}}/used")
        print(f"  2. 从页面源码获取 listing UID")
        print(f"  3. 保存 UID 到文件，每行一个")
        print(f"  4. 运行: python main.py --prices --listings-file listings.txt")
    print()


def _run_search_mode(args, paths, scraper):
    """--search: 通过 API 搜索交易卡（速度快，一条请求即返回结果）"""
    keyword = args.search.strip()

    print("=" * 60)
    print(f"搜索模式: {keyword}")
    print("=" * 60)

    # 1. 调用搜索 API（新站 snkrdunk.com/search，枚数固定为 1 枚）
    print(f"\n[1/2] 搜索: {keyword} (枚数=1枚)")
    results = search_trading_cards(
        keyword=keyword,
        max_results=args.max_matches,
    )

    if not results:
        print(f"\n未找到匹配 '{keyword}' 的卡片")
        print(f"  [HINT] 可以尝试更简单的关键词")
        print(f"  [HINT] 多个关键词用空格分隔，如: --search 'sv8 pikachu'")
        return

    # 1.5 本地二次过滤（多关键词 AND 匹配）
    if args.keywords:
        filtered = []
        for r in results:
            name = r.get("card_name", "")
            all_match = all(kw.lower() in name.lower() for kw in args.keywords)
            if all_match:
                filtered.append(r)
        print(f"\n[本地过滤] 关键词: {' & '.join(args.keywords)}")
        print(f"  过滤前: {len(results)} 张 → 过滤后: {len(filtered)} 张")
        results = filtered

    # 打印搜索结果（过滤后）
    print_search_results(results, keyword)

    # 2. 可选：保存搜索结果列表
    search_list_path = os.path.join(args.output, "search_results.json")
    save_search_results(results, search_list_path)

    # 3. 可选：爬取详细数据
    should_scrape = input(
        f"\n是否爬取这 {len(results)} 张卡片的详细数据？(y/N): "
    ).strip().lower()
    if should_scrape == "y":
        print(f"\n[2/2] 爬取 {len(results)} 张卡片详情...")
        detailed = []
        for i, r in enumerate(results):
            cid = r["id"]
            print(f"  [{i+1}/{len(results)}] 爬取 {cid} ...")
            data = fetch_product_detail(cid)
            if data:
                detailed.append(data)
            time.sleep(0.5)
        if detailed:
            if args.format in ("json", "both"):
                scraper.save_results(detailed, "trading_cards.json")
            if args.format in ("csv", "both"):
                scraper.save_csv(detailed, "trading_cards.csv")
            print_stats(detailed)
            print(f"\n详细数据已保存到 data/trading_cards.json")
        else:
            print("[INFO] 本次没有成功爬取到详情")
    else:
        print(f"\n搜索结果已保存到 {search_list_path}")
        print(f"  [HINT] 再次运行 --search '{keyword}' 并输入 y 可爬取详情")
    print()


def _show_resume_hint(paths):
    ck_size = sum(1 for _ in open(paths["checkpoint"], encoding="utf-8")) if os.path.exists(paths["checkpoint"]) else 0
    urls_size = sum(1 for _ in open(paths["urls"], encoding="utf-8")) if os.path.exists(paths["urls"]) else 0
    if 0 < ck_size < urls_size:
        print(f"\n{'=' * 60}")
        print(f"剩余 {urls_size - ck_size} 张卡片未爬取，继续运行:")
        print(f"   python main.py --resume")
        print(f"之后可检测更新:")
        print(f"   python main.py --check-updates")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
