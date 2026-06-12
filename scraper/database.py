"""
Database - MySQL 数据库连接与操作

配置（环境变量或直接修改下方默认值）:
  DB_CONNECTION, DB_HOST, DB_PORT, DB_DATABASE, DB_USERNAME, DB_PASSWORD
"""

import os
from typing import Dict, List, Optional

import pymysql
from pymysql.cursors import DictCursor

# 数据库配置（优先从环境变量读取）
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "8.210.90.110"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "database": os.getenv("DB_DATABASE", "lucku"),
    "user": os.getenv("DB_USERNAME", "lucku"),
    "password": os.getenv("DB_PASSWORD", "lucku"),
    "charset": "utf8mb4",
}

TABLE_NAME = "trading_cards"


def get_connection():
    """获取数据库连接"""
    return pymysql.connect(**DB_CONFIG)


def ensure_table():
    """
    确保目标表存在，不存在则自动创建。
    字段设计覆盖 search_api 和 card_scraper 两个来源的全部字段。
    """
    sql = f"""
    CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
        `id` VARCHAR(32) NOT NULL PRIMARY KEY,
        `card_name` VARCHAR(255) DEFAULT '' COMMENT '卡片名称',
        `brand` VARCHAR(128) DEFAULT '' COMMENT '品牌',
        `category` VARCHAR(128) DEFAULT '' COMMENT '品类',
        `card_type` VARCHAR(32) DEFAULT '' COMMENT '类型(single/box_pack)',
        `min_price` DECIMAL(12,2) DEFAULT NULL COMMENT '最低价',
        `min_price_format` VARCHAR(64) DEFAULT '' COMMENT '最低价格式化',
        `min_price_currency` VARCHAR(16) DEFAULT '' COMMENT '最低价货币',
        `listing_count` INT DEFAULT 0 COMMENT '在售数量',
        `offer_count` INT DEFAULT 0 COMMENT '求购数量',
        `all_listing_count` VARCHAR(32) DEFAULT '' COMMENT '全部listing',
        `used_min_price` DECIMAL(12,2) DEFAULT NULL COMMENT '二手最低价',
        `used_min_price_format` VARCHAR(64) DEFAULT '' COMMENT '二手最低价格式化',
        `used_min_price_currency` VARCHAR(16) DEFAULT '' COMMENT '二手货币',
        `used_listing_count` INT DEFAULT 0 COMMENT '二手listing数',
        `max_price` DECIMAL(12,2) DEFAULT NULL COMMENT '最高价',
        `max_price_format` VARCHAR(64) DEFAULT '' COMMENT '最高价格式化',
        `release_date` VARCHAR(32) DEFAULT '' COMMENT '发布日期',
        `product_code` VARCHAR(64) DEFAULT '' COMMENT '产品编码',
        `product_number` VARCHAR(64) DEFAULT '' COMMENT '产品编号',
        `thumbnail_url` VARCHAR(512) DEFAULT '' COMMENT '缩略图URL',
        `description` TEXT COMMENT '描述',
        `image_count` INT DEFAULT 0 COMMENT '图片数量',
        `url` VARCHAR(512) DEFAULT '' COMMENT '卡片URL',
        `title` VARCHAR(255) DEFAULT '' COMMENT '页面标题',
        `is_trading_card` TINYINT(1) DEFAULT 0 COMMENT '是否是交易卡',
        `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '导入时间',
        UNIQUE KEY `uk_id` (`id`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
        conn.commit()
    finally:
        conn.close()


def safe_decimal(value) -> Optional[float]:
    """安全转换为 Decimal 兼容的 float 或 None"""
    if value is None:
        return None
    try:
        v = float(value)
        return v
    except (ValueError, TypeError):
        return None


def safe_int(value) -> int:
    """安全转 int"""
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


def insert_or_update_card(card: Dict) -> bool:
    """插入或更新一张卡片（按 id 去重）"""
    sql = f"""
    INSERT INTO `{TABLE_NAME}` (
        `id`, `card_name`, `brand`, `category`, `card_type`,
        `min_price`, `min_price_format`, `min_price_currency`,
        `listing_count`, `offer_count`, `all_listing_count`,
        `used_min_price`, `used_min_price_format`, `used_min_price_currency`,
        `used_listing_count`,
        `max_price`, `max_price_format`,
        `release_date`, `product_code`, `product_number`,
        `thumbnail_url`, `description`, `image_count`,
        `url`, `title`, `is_trading_card`
    ) VALUES (
        %(id)s, %(card_name)s, %(brand)s, %(category)s, %(card_type)s,
        %(min_price)s, %(min_price_format)s, %(min_price_currency)s,
        %(listing_count)s, %(offer_count)s, %(all_listing_count)s,
        %(used_min_price)s, %(used_min_price_format)s, %(used_min_price_currency)s,
        %(used_listing_count)s,
        %(max_price)s, %(max_price_format)s,
        %(release_date)s, %(product_code)s, %(product_number)s,
        %(thumbnail_url)s, %(description)s, %(image_count)s,
        %(url)s, %(title)s, %(is_trading_card)s
    ) ON DUPLICATE KEY UPDATE
        `card_name` = VALUES(`card_name`),
        `brand` = VALUES(`brand`),
        `category` = VALUES(`category`),
        `card_type` = VALUES(`card_type`),
        `min_price` = VALUES(`min_price`),
        `min_price_format` = VALUES(`min_price_format`),
        `min_price_currency` = VALUES(`min_price_currency`),
        `listing_count` = VALUES(`listing_count`),
        `offer_count` = VALUES(`offer_count`),
        `all_listing_count` = VALUES(`all_listing_count`),
        `used_min_price` = VALUES(`used_min_price`),
        `used_min_price_format` = VALUES(`used_min_price_format`),
        `used_min_price_currency` = VALUES(`used_min_price_currency`),
        `used_listing_count` = VALUES(`used_listing_count`),
        `max_price` = VALUES(`max_price`),
        `max_price_format` = VALUES(`max_price_format`),
        `release_date` = VALUES(`release_date`),
        `product_code` = VALUES(`product_code`),
        `product_number` = VALUES(`product_number`),
        `thumbnail_url` = VALUES(`thumbnail_url`),
        `description` = VALUES(`description`),
        `image_count` = VALUES(`image_count`),
        `url` = VALUES(`url`),
        `title` = VALUES(`title`),
        `is_trading_card` = VALUES(`is_trading_card`)
    """

    params = {
        "id": str(card.get("id", "")),
        "card_name": card.get("card_name", "") or card.get("title", ""),
        "brand": card.get("brand", ""),
        "category": card.get("category", ""),
        "card_type": card.get("card_type", ""),
        "min_price": safe_decimal(card.get("min_price")),
        "min_price_format": card.get("min_price_format", ""),
        "min_price_currency": card.get("min_price_currency", ""),
        "listing_count": safe_int(card.get("listing_count")),
        "offer_count": safe_int(card.get("offer_count")),
        "all_listing_count": str(card.get("all_listing_count", "")),
        "used_min_price": safe_decimal(card.get("used_min_price")),
        "used_min_price_format": card.get("used_min_price_format", ""),
        "used_min_price_currency": card.get("used_min_price_currency", ""),
        "used_listing_count": safe_int(card.get("used_listing_count")),
        "max_price": safe_decimal(card.get("max_price") or card.get("max_price_amount")),
        "max_price_format": card.get("max_price_format", ""),
        "release_date": str(card.get("release_date", "") or card.get("released_at", "")),
        "product_code": card.get("product_code", "") or card.get("product_number", ""),
        "product_number": card.get("product_number", ""),
        "thumbnail_url": card.get("thumbnail_url", ""),
        "description": card.get("description", ""),
        "image_count": safe_int(card.get("image_count") or card.get("imageCount")),
        "url": card.get("url", ""),
        "title": card.get("title", ""),
        "is_trading_card": 1 if card.get("is_trading_card") else 0,
    }

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount > 0
    except pymysql.Error as e:
        raise RuntimeError(f"MySQL 写入失败: {e}")
    finally:
        conn.close()


def import_cards(cards: List[Dict]) -> Dict:
    """
    批量导入卡片到 MySQL

    Args:
        cards: 卡片数据列表

    Returns:
        {"total": 总数, "success": 成功数, "failed": 失败数, "success_ids": [成功ID], "errors": [错误信息]}
    """
    ensure_table()
    success = 0
    failed = 0
    success_ids = []
    errors = []

    for card in cards:
        try:
            insert_or_update_card(card)
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
