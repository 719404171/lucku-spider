"""
Database - MySQL 数据库连接与操作

配置（环境变量或直接修改下方默认值）:
  DB_HOST, DB_PORT, DB_DATABASE, DB_USERNAME, DB_PASSWORD
"""

import json
import os
from typing import Dict, List, Optional

import pymysql

# 数据库配置（优先从环境变量读取）
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "8.210.90.110"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "database": os.getenv("DB_DATABASE", "lucku"),
    "user": os.getenv("DB_USERNAME", "lucku"),
    "password": os.getenv("DB_PASSWORD", "lucku"),
    "charset": "utf8mb4",
}

TABLE_NAME = "spider_cards"


# ============================================================
#  字段映射：爬虫数据字段 → spider_cards 表字段
# ============================================================
FIELD_MAP = {
    "id": "crawler_id",
    "url": "crawler_url",
    "title": "en_card_name",
    "card_name": "card_name",
    "brand": "card_brand",
    "category": "card_category",
    "min_price": "card_cost",
    "product_code": "card_code",
    "thumbnail_url": "card_img",
    "card_type": "card_type",
    "description": "card_describe",
}


def get_connection():
    """获取数据库连接"""
    return pymysql.connect(**DB_CONFIG)


def ensure_table():
    """
    确保 spider_cards 表存在，不存在则自动创建。
    包含爬虫数据和成色价格字段。
    """
    sql = f"""
    CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
        `id` INT AUTO_INCREMENT PRIMARY KEY,
        `crawler_id` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '爬虫ID',
        `crawler_url` VARCHAR(512) DEFAULT '' COMMENT '爬虫来源URL',
        `en_card_name` VARCHAR(512) DEFAULT '' COMMENT '英文卡名',
        `card_name` VARCHAR(512) DEFAULT '' COMMENT '卡片名称',
        `card_brand` VARCHAR(256) DEFAULT '' COMMENT '品牌',
        `card_category` VARCHAR(256) DEFAULT '' COMMENT '品类',
        `card_cost` DECIMAL(12,2) DEFAULT NULL COMMENT '最低价',
        `card_code` VARCHAR(128) DEFAULT '' COMMENT '产品编码',
        `card_img` VARCHAR(512) DEFAULT '' COMMENT '缩略图URL',
        `card_type` VARCHAR(64) DEFAULT '' COMMENT '类型',
        `card_describe` TEXT COMMENT '描述',
        `deal_price` DECIMAL(12,2) DEFAULT NULL COMMENT '选中成色价格',
        `deal_format` VARCHAR(64) DEFAULT '' COMMENT '选中成色价格格式',
        `deal_condition` VARCHAR(32) DEFAULT '' COMMENT '选中成色等级（如 PSA 10）',
        `condition_prices` LONGTEXT DEFAULT NULL COMMENT '全部成色价格（JSON）',
        `is_update` TINYINT(1) DEFAULT 1 COMMENT '是否自动更新 1是 0否',
        `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间',
        INDEX `idx_crawler_id` (`crawler_id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='爬取卡片数据'
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
        conn.commit()
    except Exception as e:
        raise RuntimeError(f"创建 spider_cards 表失败: {e}")
    finally:
        conn.close()


def ensure_settings_table():
    """确保 app_settings 表存在"""
    sql = """
    CREATE TABLE IF NOT EXISTS `app_settings` (
        `key` VARCHAR(64) PRIMARY KEY,
        `value` TEXT DEFAULT NULL,
        `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '更新时间'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8 COMMENT='应用设置'
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            # 插入默认值
            defaults = {
                "auto_update_enabled": "false",
                "auto_update_time1": "08:00",
                "auto_update_time2": "20:00",
            }
            for k, v in defaults.items():
                cursor.execute(
                    "INSERT IGNORE INTO `app_settings` (`key`, `value`) VALUES (%s, %s)",
                    (k, v)
                )
        conn.commit()
    except Exception as e:
        raise RuntimeError(f"创建 app_settings 表失败: {e}")
    finally:
        conn.close()


def db_load_settings() -> dict:
    """从 app_settings 表读取所有设置"""
    ensure_settings_table()
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT `key`, `value` FROM `app_settings`")
            rows = cursor.fetchall()
            result = {}
            for r in rows:
                val = r["value"]
                if val == "true":
                    val = True
                elif val == "false":
                    val = False
                result[r["key"]] = val
            return result
    except Exception:
        return {}
    finally:
        conn.close()


def db_save_setting(key: str, value):
    """保存单条设置到 app_settings 表"""
    if isinstance(value, bool):
        value = "true" if value else "false"
    else:
        value = str(value)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO `app_settings` (`key`, `value`) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE `value` = %s",
                (key, value, value)
            )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


_default_settings = {
    "enabled": False,
    "time1": "08:00",
    "time2": "20:00",
}


def safe_decimal(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def insert_card(card: Dict) -> bool:
    """
    向 spider_cards 表插入一条数据。
    按 crawler_id 去重（先删再插）。
    """
    params = {
        "crawler_id": str(card.get("id", "")),
        "crawler_url": str(card.get("url", "")),
        "en_card_name": str(card.get("title", "")),
        "card_name": str(card.get("card_name", "") or card.get("title", "")),
        "card_brand": str(card.get("brand", "")),
        "card_category": str(card.get("category", "")),
        "card_cost": safe_decimal(card.get("min_price")),
        "card_code": str(card.get("product_code", "") or card.get("product_number", "")),
        "card_img": str(card.get("thumbnail_url", "")),
        "card_type": str(card.get("card_type", "")),
        "card_describe": str(card.get("description", "")),
        "deal_price": safe_decimal(card.get("deal_price")),
        "deal_format": str(card.get("deal_format", "")),
        "deal_condition": str(card.get("deal_condition", "")),
        "condition_prices": json.dumps(card.get("condition_prices", {}), ensure_ascii=False) if card.get("condition_prices") else None,
    }

    # 根据类型决定是否自动更新：box_pack 不更新，single 更新
    raw_type = str(card.get("card_type", "") or card.get("type", ""))
    card_type_val = raw_type.lower().strip()
    if card_type_val == "box_pack":
        is_update = 0
    elif card_type_val == "single":
        is_update = 1
    else:
        is_update = 1  # 默认启用更新
    params["is_update"] = is_update
    print(f"[DEBUG] insert_card {card.get('id','?')}: card_type='{raw_type}' → is_update={is_update}")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 查找是否存在相同 crawler_id + deal_condition 的记录
            deal_cond = params["deal_condition"]
            cursor.execute(
                f"SELECT `id` FROM `{TABLE_NAME}` WHERE `crawler_id` = %s AND `deal_condition` = %s ORDER BY `id` DESC LIMIT 1",
                (params["crawler_id"], deal_cond)
            )
            existing = cursor.fetchone()

            if existing:
                # 相同卡牌 + 相同成色 → 更新价格
                cursor.execute(f"""
                    UPDATE `{TABLE_NAME}` SET
                        `card_cost` = %(card_cost)s,
                        `deal_price` = %(deal_price)s,
                        `deal_format` = %(deal_format)s,
                        `condition_prices` = %(condition_prices)s,
                        `updated_at` = NOW()
                    WHERE `id` = %(existing_id)s
                """, {**params, "existing_id": existing[0]})
            else:
                # 相同卡牌 + 不同成色（或新卡牌）→ 插入新记录
                cursor.execute(f"""
                    INSERT INTO `{TABLE_NAME}` (
                        `crawler_id`, `crawler_url`, `en_card_name`, `card_name`,
                        `card_brand`, `card_category`, `card_cost`, `card_code`,
                        `card_img`, `card_type`, `card_describe`,
                        `deal_price`, `deal_format`, `deal_condition`, `condition_prices`,
                        `is_update`
                    ) VALUES (
                        %(crawler_id)s, %(crawler_url)s, %(en_card_name)s, %(card_name)s,
                        %(card_brand)s, %(card_category)s, %(card_cost)s, %(card_code)s,
                        %(card_img)s, %(card_type)s, %(card_describe)s,
                        %(deal_price)s, %(deal_format)s, %(deal_condition)s, %(condition_prices)s,
                        %(is_update)s
                    )
                """, params)
            conn.commit()
            return True
    except pymysql.Error as e:
        conn.rollback()
        raise RuntimeError(f"MySQL 写入失败: {e}")
    finally:
        conn.close()


def delete_card_by_crawler_id(crawler_id: str) -> bool:
    """根据 crawler_id 删除 spider_cards 表中的所有匹配记录"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM `{TABLE_NAME}` WHERE `crawler_id` = %s",
                (crawler_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
    except pymysql.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def delete_card_by_row_id(row_id: int) -> bool:
    """根据 MySQL 自增 id 删除单条记录"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM `{TABLE_NAME}` WHERE `id` = %s",
                (row_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
    except pymysql.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_card_recycle_percent() -> int:
    """从 shop_setting 表读取 card_recycle_percent（卡牌回收百分比）"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT `card_recycle_percent` FROM `shop_setting` LIMIT 1")
            row = cursor.fetchone()
            if row:
                return int(row[0])
            return 0
    except Exception:
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_card_sell_percent() -> int:
    """从 shop_setting 表读取 card_sell_percent（卡牌售卖百分比）"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT `card_sell_percent` FROM `shop_setting` LIMIT 1")
            row = cursor.fetchone()
            if row:
                return int(row[0])
            return 0
    except Exception:
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def update_card_price_by_crawler_id(crawler_id: str, deal_price: float, recycle_percent: int) -> bool:
    """
    根据 crawler_id 更新 card 表中所有匹配记录（更新价格时同步）：
      card_price   = 基准价(deal_price) × 回收百分比 / 100
      card_recycle = 基准价 × 回收百分比 / 100（与 card_price 相同）
      card_cost    = 基准价(deal_price)
    """
    if deal_price is None or recycle_percent <= 0:
        return False
    card_price = deal_price * recycle_percent / 100
    base = round(float(deal_price), 2)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE `card` SET `card_price` = %s, `card_recycle` = %s, "
                "`card_cost` = %s, `updated_at` = NOW() WHERE `crawler_id` = %s",
                (round(card_price, 2), round(card_price, 2), base, crawler_id)
            )
            conn.commit()
            return cursor.rowcount > 0
    except pymysql.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def update_product_price_by_crawler_id(crawler_id: str, deal_price: float, sell_percent: int) -> bool:
    """
    根据 crawler_id 更新 product 表中所有匹配记录的 product_price。
    product_price = deal_price * sell_percent / 100
    """
    if deal_price is None or sell_percent <= 0:
        return False
    product_price = deal_price * sell_percent / 100
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE `product` SET `product_price` = %s WHERE `crawler_id` = %s",
                (round(product_price, 2), crawler_id)
            )
            conn.commit()
            return cursor.rowcount > 0
    except pymysql.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def update_card_conditions(crawler_id: str, min_price: float, condition_prices: dict,
                            deal_condition: str = None, deal_price: float = None, deal_format: str = None) -> bool:
    """
    根据 crawler_id 更新卡片的成色价格和最低价（更新最新一条记录）。
    如果传入了 deal_condition/deal_price/deal_format，也一并更新。
    """
    set_clause = "`card_cost` = %(card_cost)s, `condition_prices` = %(condition_prices)s, `updated_at` = NOW()"
    params = {
        "card_cost": safe_decimal(min_price),
        "condition_prices": json.dumps(condition_prices, ensure_ascii=False) if condition_prices else None,
        "crawler_id": crawler_id,
    }
    if deal_condition is not None:
        set_clause += ", `deal_condition` = %(deal_condition)s"
        params["deal_condition"] = str(deal_condition)
    if deal_price is not None:
        set_clause += ", `deal_price` = %(deal_price)s"
        params["deal_price"] = safe_decimal(deal_price)
    if deal_format is not None:
        set_clause += ", `deal_format` = %(deal_format)s"
        params["deal_format"] = str(deal_format)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"""
                UPDATE `{TABLE_NAME}`
                SET {set_clause}
                WHERE `crawler_id` = %(crawler_id)s
                ORDER BY `id` DESC
                LIMIT 1
            """, params)
            conn.commit()
            return cursor.rowcount > 0
    except pymysql.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def import_cards(cards: List[Dict]) -> Dict:
    """
    批量导入卡片到 MySQL

    Returns:
        {"total": 总数, "success": 成功数, "failed": 失败数,
         "success_ids": [成功ID], "errors": [错误信息]}
    """
    ensure_table()

    success = 0
    failed = 0
    success_ids = []
    errors = []

    for card in cards:
        try:
            insert_card(card)
            success += 1
            success_ids.append(str(card.get("id", "")))
        except Exception as e:
            card_id = card.get("id", "?")
            err_msg = f"[{card_id}] {e}"
            errors.append(err_msg)
            failed += 1

    return {
        "total": len(cards),
        "success": success,
        "failed": failed,
        "success_ids": success_ids,
        "errors": errors,
    }


def get_all_imported_ids() -> set:
    """从 MySQL 查询所有已导入的卡片 ID（crawler_id）"""
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT `crawler_id` FROM `{TABLE_NAME}` WHERE `crawler_id` != ''")
            return {str(row[0]) for row in cursor.fetchall()}
    except Exception:
        return set()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _update_deal_condition(crawler_id: str, deal_condition: str):
    """将推断出的 deal_condition 写回 MySQL（更新所有相同 crawler_id 的记录）"""
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE `{TABLE_NAME}` SET `deal_condition` = %s WHERE `crawler_id` = %s",
                (deal_condition, crawler_id)
            )
            conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def set_card_is_update(crawler_id: str, is_update: bool) -> bool:
    """设置指定 crawler_id 的 is_update 状态"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE `{TABLE_NAME}` SET `is_update` = %s, `updated_at` = NOW() WHERE `crawler_id` = %s",
                (1 if is_update else 0, crawler_id)
            )
            conn.commit()
            return cursor.rowcount > 0
    except pymysql.Error:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_all_imported_cards(only_update=True) -> list:
    """从 MySQL 查询所有导入卡片的完整信息（不去重，取出全部记录）
    only_update=True: 只返回 is_update=1 的卡片（供自动更新用）
    only_update=False: 返回全部卡片（供统计页面展示）
    """
    try:
        conn = get_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            where = "WHERE `is_update` = 1" if only_update else ""
            cursor.execute(f"""
                SELECT `id`, `crawler_id`, `card_name`, `en_card_name`, `card_cost`, `card_brand`,
                       `card_category`, `card_code`, `card_img`, `card_type`, `card_describe`,
                       `deal_price`, `deal_format`, `deal_condition`, `condition_prices`, `is_update`, `created_at`, `updated_at`
                FROM `{TABLE_NAME}`
                {where}
                ORDER BY `created_at` DESC
            """)
            rows = cursor.fetchall()
            result = []
            for r in rows:
                cp = None
                if r.get("condition_prices"):
                    try:
                        cp = json.loads(r["condition_prices"])
                    except (json.JSONDecodeError, TypeError):
                        cp = None
                result.append({
                    "row_id": r.get("id"),
                    "id": r.get("crawler_id", ""),
                    "card_name": r.get("card_name", r.get("en_card_name", "")),
                    "card_brand": r.get("card_brand", ""),
                    "card_cost": float(r["card_cost"]) if r.get("card_cost") is not None else None,
                    "deal_price": float(r["deal_price"]) if r.get("deal_price") is not None else None,
                    "deal_format": r.get("deal_format", ""),
                    "deal_condition": r.get("deal_condition", ""),
                    "card_type": r.get("card_type", ""),
                    "card_img": r.get("card_img", ""),
                    "condition_prices": cp,
                    "is_update": bool(r.get("is_update", 1)),
                    "created_at": str(r.get("created_at", "")),
                    "updated_at": str(r.get("updated_at", "")),
                })

            # 对没有 deal_condition 但有 condition_prices 的卡片，根据 deal_price 反查成色
            deal_price_grades = ["A", "B", "C", "D", "PSA 10", "PSA 9", "PSA 8 or under", "BGS 10 BL", "BGS 10 GL"]
            for card in result:
                if not card["deal_condition"] and card["condition_prices"] and card["deal_price"] is not None:
                    dp = card["deal_price"]
                    cp = card["condition_prices"]
                    matched = None
                    for g in deal_price_grades:
                        cp_g = cp.get(g, {})
                        if cp_g and cp_g.get("price") is not None and abs(float(cp_g["price"]) - dp) < 0.01:
                            matched = g
                            break
                    if not matched and card.get("deal_format"):
                        df = card["deal_format"]
                        for g in deal_price_grades:
                            cp_g = cp.get(g, {})
                            if cp_g and cp_g.get("format") == df:
                                matched = g
                                break
                    if matched:
                        card["deal_condition"] = matched
                        # 写回数据库
                        _update_deal_condition(card["id"], matched)
            return result
    except Exception:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def debug_table_structure() -> dict:
    """调试用：查看 spider_cards 表结构和当前数据量"""
    result = {"exists": False, "columns": [], "row_count": 0, "error": None}
    try:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute(f"DESCRIBE `{TABLE_NAME}`")
            result["columns"] = [f"{row[0]} ({row[1]})" for row in cursor.fetchall()]
            result["exists"] = True

            cursor.execute(f"SELECT COUNT(*) FROM `{TABLE_NAME}`")
            result["row_count"] = cursor.fetchone()[0]
        conn.close()
    except Exception as e:
        result["error"] = str(e)
    return result
