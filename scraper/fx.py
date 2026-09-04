"""
汇率服务 - JPY → HKD
====================
规则（按需求）：
  - 每次查询/更新任务开始时会尝试抓取一次最新汇率；
  - 抓到新汇率 -> 存入 fx_rate 表并立即使用；
  - 抓取失败（无新汇率） -> 使用 fx_rate 表中最新的一条；
  - 价格一律以「最新汇率」把日元换算成港币后展示与入库，不再存日元。

为免批量爬取时每张卡都打一次汇率接口，模块内做了进程级短缓存（默认 5 分钟），
并会把成功的抓取写回数据库。
"""

import json
import time
import urllib.request

from typing import Dict, Optional

RATE_API = "https://open.er-api.com/v6/latest/JPY"
BASE_CURRENCY = "JPY"
QUOTE_CURRENCY = "HKD"

_CACHE: Dict = {"rate": None, "source": "", "fetched_at": "", "ts": 0.0, "failed_ts": 0.0}
_CACHE_TTL = 300          # 成功结果的进程缓存时间（秒）
_FAIL_RETRY_TTL = 60      # 抓取失败后多久再重试（秒）


def ensure_fx_table():
    """确保 fx_rate 汇率表存在"""
    from scraper.database import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS `fx_rate` (
                `base` VARCHAR(8) NOT NULL COMMENT '源币种',
                `quote` VARCHAR(8) NOT NULL COMMENT '目标币种',
                `rate` DECIMAL(18,8) NOT NULL COMMENT '1 base = ? quote',
                `source` VARCHAR(128) DEFAULT '' COMMENT '数据来源',
                `fetched_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '抓取时间',
                PRIMARY KEY (`base`, `quote`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='汇率表(JPY->HKD)'
            """)
        conn.commit()
    finally:
        conn.close()


def get_latest_from_db() -> Optional[Dict]:
    """读取数据库中最新汇率"""
    ensure_fx_table()
    from scraper.database import get_connection
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT `base`,`quote`,`rate`,`source`,`fetched_at` FROM `fx_rate` "
                "WHERE `base`=%s AND `quote`=%s LIMIT 1",
                (BASE_CURRENCY, QUOTE_CURRENCY),
            )
            row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "rate": float(row[2]),
                "source": row[3] or "",
                "fetched_at": str(row[4] or ""),
            }
    except Exception as e:
        print(f"[WARN] 读取数据库汇率失败: {e}")
    return None


def save_to_db(rate: float, source: str):
    """保存最新汇率到数据库"""
    ensure_fx_table()
    from scraper.database import get_connection
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO `fx_rate` (`base`,`quote`,`rate`,`source`,`fetched_at`) "
                "VALUES (%s,%s,%s,%s,NOW()) "
                "ON DUPLICATE KEY UPDATE `rate`=%s, `source`=%s, `fetched_at`=NOW()",
                (BASE_CURRENCY, QUOTE_CURRENCY, rate, source, rate, source),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WARN] 写入数据库汇率失败: {e}")


def _fetch_remote() -> Optional[Dict]:
    """向汇率接口抓取最新 JPY→HKD"""
    try:
        req = urllib.request.Request(RATE_API, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        rate = data.get("rates", {}).get("HKD")
        if not rate:
            return None
        return {
            "rate": float(rate),
            "source": "open.er-api.com",
            "fetched_at": data.get("time_last_update_utc", ""),
        }
    except Exception as e:
        print(f"[WARN] 抓取汇率失败: {e}")
        return None


def get_hkd_rate(refresh: bool = False) -> Optional[Dict]:
    """
    获取最新汇率信息（1 JPY = ? HKD）。

    规则：
      1. 若距上次成功抓取 < _CACHE_TTL 且未强制刷新，直接返回缓存；
      2. 尝试抓取接口 -> 成功则写库并缓存使用；
      3. 接口失败 -> 读取数据库最新一条；
      4. 都不可用 -> 返回 None。
    """
    now = time.time()
    if not refresh and _CACHE["rate"] is not None and now - _CACHE["ts"] < _CACHE_TTL:
        return dict(_CACHE)

    # 失败后短暂冷却，避免频繁请求
    if not refresh and now - _CACHE["failed_ts"] < _FAIL_RETRY_TTL and _CACHE["rate"] is None:
        db = get_latest_from_db()
        return db

    remote = _fetch_remote()
    if remote:
        save_to_db(remote["rate"], remote["source"])
        # 以数据库写入时间(本地)作为更新时间，更直观
        db = get_latest_from_db()
        _CACHE.update({
            "rate": remote["rate"],
            "source": remote["source"],
            "fetched_at": (db or {}).get("fetched_at") or remote["fetched_at"],
            "ts": now,
            "failed_ts": 0.0,
        })
        return dict(_CACHE)

    # 抓取失败：用数据库最新
    _CACHE["failed_ts"] = now
    db = get_latest_from_db()
    if db:
        _CACHE.update({"rate": db["rate"], "source": db["source"], "fetched_at": db["fetched_at"], "ts": now})
        return dict(_CACHE)
    return None


def jpy_to_hkd(price_jpy) -> Optional[float]:
    """日元金额 -> 港币金额（2 位小数）；汇率为空时返回 None"""
    if price_jpy is None:
        return None
    try:
        jpy = float(price_jpy)
    except (TypeError, ValueError):
        return None
    info = get_hkd_rate()
    if not info or not info.get("rate"):
        return None
    return round(jpy * info["rate"], 2)


def format_hkd(price_hkd) -> str:
    """港币金额 -> 'HK$1,234.56'"""
    if price_hkd is None:
        return "-"
    return f"HK${price_hkd:,.2f}"
