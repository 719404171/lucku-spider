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
        `condition_prices` LONGTEXT DEFAULT NULL COMMENT '全部成色价格（JSON）',
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
        "condition_prices": json.dumps(card.get("condition_prices", {}), ensure_ascii=False) if card.get("condition_prices") else None,
    }

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 按 crawler_id 删除旧数据
            cursor.execute(
                f"DELETE FROM `{TABLE_NAME}` WHERE `crawler_id` = %(crawler_id)s",
                {"crawler_id": params["crawler_id"]}
            )
            conn.commit()

            # 插入新数据
            cursor.execute(f"""
                INSERT INTO `{TABLE_NAME}` (
                    `crawler_id`, `crawler_url`, `en_card_name`, `card_name`,
                    `card_brand`, `card_category`, `card_cost`, `card_code`,
                    `card_img`, `card_type`, `card_describe`,
                    `deal_price`, `deal_format`, `condition_prices`
                ) VALUES (
                    %(crawler_id)s, %(crawler_url)s, %(en_card_name)s, %(card_name)s,
                    %(card_brand)s, %(card_category)s, %(card_cost)s, %(card_code)s,
                    %(card_img)s, %(card_type)s, %(card_describe)s,
                    %(deal_price)s, %(deal_format)s, %(condition_prices)s
                )
            """, params)
            conn.commit()
            return True
    except pymysql.Error as e:
        conn.rollback()
        raise RuntimeError(f"MySQL 写入失败: {e}")
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


def get_all_imported_cards() -> list:
    """从 MySQL 查询所有导入卡片的完整信息"""
    try:
        conn = get_connection()
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(f"""
                SELECT `crawler_id`, `card_name`, `en_card_name`, `card_cost`, `card_brand`,
                       `card_category`, `card_code`, `card_img`, `card_type`, `card_describe`,
                       `deal_price`, `deal_format`, `condition_prices`, `created_at`
                FROM `{TABLE_NAME}`
                ORDER BY `created_at` DESC
            """)
            rows = cursor.fetchall()
            # 转为更友好的格式
            result = []
            for r in rows:
                cp = None
                if r.get("condition_prices"):
                    try:
                        cp = json.loads(r["condition_prices"])
                    except (json.JSONDecodeError, TypeError):
                        cp = None
                result.append({
                    "id": r.get("crawler_id", ""),
                    "card_name": r.get("card_name", r.get("en_card_name", "")),
                    "card_brand": r.get("card_brand", ""),
                    "card_cost": float(r["card_cost"]) if r.get("card_cost") is not None else None,
                    "deal_price": float(r["deal_price"]) if r.get("deal_price") is not None else None,
                    "deal_format": r.get("deal_format", ""),
                    "card_img": r.get("card_img", ""),
                    "condition_prices": cp,
                    "created_at": str(r.get("created_at", "")),
                })
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
