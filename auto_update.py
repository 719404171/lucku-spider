"""
SNKRDUNK 自动价格更新脚本
========================
用于 宝塔面板 定时任务调用，根据 Web UI 中设置的时间和成色自动更新已导入卡牌的最新价格。

宝塔定时任务配置示例（每 10 分钟执行一次）：
    cd /www/Python/snkrdunk  && /www/server/pyporject_evn/SpiderCard/bin/python auto_update.py >> logs/auto_update.log 2>&1

脚本逻辑：
    1. 从 MySQL 读取定时设置（启用状态、时间1、时间2、选中成色）
    2. 检查当前时间是否匹配设定的时间点（误差 6 分钟内）
    3. 如果启用且时间匹配，遍历 spider_cards 表中的卡片
    4. 调用 fetch_condition_prices 刷新各成色价格
    5. 更新数据库中对应记录的 card_cost、condition_prices、deal_price 等
"""

import json
import os
import sys
from datetime import datetime

# ============================================================
#  路径设置 —— 宝塔部署时根据实际路径修改
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def log(msg: str):
    """带时间戳的日志输出"""
    ts = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{ts} {msg}"
    print(line)
    # 同时写入日志文件
    log_file = os.path.join(LOG_DIR, "auto_update.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_settings():
    """从 MySQL 读取自动更新配置"""
    try:
        from scraper.database import db_load_settings
        raw = db_load_settings()
        return {
            "enabled": bool(raw.get("auto_update_enabled", False)),
            "time1": str(raw.get("auto_update_time1", "08:00")),
            "time2": str(raw.get("auto_update_time2", "20:00")),
        }
    except Exception as e:
        log(f"读取数据库设置失败: {e}")
        return None


def is_time_match(settings) -> bool:
    """
    检查当前时间是否匹配设定的时间点。
    允许前后 6 分钟误差。
    """
    now = datetime.now()
    now_minutes = now.hour * 60 + now.minute

    t1 = settings.get("time1", "08:00")
    t2 = settings.get("time2", "20:00")

    def _parse_minutes(t_str: str) -> int:
        parts = t_str.strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])

    for t_str in [t1, t2]:
        target = _parse_minutes(t_str)
        if abs(now_minutes - target) <= 6:
            return True
    return False


def run_price_update():
    """
    执行价格更新：
    1. 从 spider_cards 表获取所有已导入卡片（按 crawler_id 去重取最新）
    2. 调用 fetch_condition_prices 刷新价格
    3. 写回数据库
    """
    log("=" * 50)
    log("开始价格更新...")

    try:
        from scraper.database import get_all_imported_cards, update_card_conditions
        from scraper.search_api import fetch_condition_prices
    except ImportError as e:
        log(f"模块导入失败，请检查环境: {e}")
        return

    # 获取所有卡片
    all_cards = get_all_imported_cards()
    if not all_cards:
        log("数据库中没有卡片，跳过")
        return

    # 按 crawler_id 去重，只保留每个 ID 最新一条
    seen = set()
    cards = []
    for c in all_cards:
        if c["id"] and c["id"] not in seen:
            seen.add(c["id"])
            cards.append(c)

    total = len(cards)
    success = 0
    fail = 0
    log(f"共 {total} 张卡片需要更新")

    for idx, card in enumerate(cards, 1):
        cid = card["id"]
        try:
            prices = fetch_condition_prices(cid, timeout=10)
            if not prices:
                fail += 1
                log(f"  [{idx}/{total}] {cid} — 获取价格为空")
                continue

            # 计算所有成色中的最低价
            vals = [v["price"] for v in prices.values() if v and v.get("price") is not None]
            min_price = min(vals) if vals else card.get("card_cost")

            # 保留原来的选中成色，用新价格更新
            old_condition = card.get("deal_condition")
            deal_price = None
            deal_format = None
            if old_condition and old_condition in prices:
                cp = prices[old_condition]
                if cp and cp.get("price") is not None:
                    deal_price = float(cp["price"])
                    deal_format = cp.get("format", f"${deal_price:.2f}")

            # 更新数据库
            updated = update_card_conditions(
                cid,
                min_price,
                prices,
                deal_condition=old_condition,
                deal_price=deal_price,
                deal_format=deal_format,
            )
            if updated:
                success += 1
            else:
                fail += 1
                log(f"  [{idx}/{total}] {cid} — 数据库更新失败")

        except Exception as e:
            fail += 1
            log(f"  [{idx}/{total}] {cid} — 错误: {e}")

        if idx % 10 == 0:
            log(f"  进度: {idx}/{total} (成功 {success}, 失败 {fail})")

    log(f"更新完成！成功 {success} 张，失败 {fail} 张，共 {total} 张")
    log("=" * 50)


def main():
    log("自动更新脚本启动")

    # 1. 读取设置
    settings = load_settings()
    if settings is None:
        log("无法读取设置，将执行一次完整更新")
        run_price_update()
        return

    log(f"当前设置: enabled={settings['enabled']}, time1={settings['time1']}, time2={settings['time2']}")

    # 2. 检查是否启用
    if not settings["enabled"]:
        log("自动更新未启用（enabled=false），跳过本次执行")
        return

    # 3. 执行更新
    # 【测试模式】临时跳过时间匹配检查，改为直接执行。
    # 测试完成后，恢复为下面的代码：
    #
    # if not is_time_match(settings):
    #     now_str = datetime.now().strftime("%H:%M")
    #     log(f"当前时间 {now_str} 未匹配 {settings['time1']} / {settings['time2']}（误差 6 分钟内），跳过")
    #     return
    #
    log("测试模式 — 跳过时间检查，直接执行更新")
    run_price_update()


if __name__ == "__main__":
    main()
