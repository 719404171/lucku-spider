"""
SNKRDUNK Trading Card Web UI - Flask 后端
提供搜索、爬取、数据展示的 Web 界面
"""
import json
import os
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.search_api import search_trading_cards, print_search_results
from scraper.card_scraper import CardScraper
from scraper.sitemap_parser import discover_all_card_urls

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 全局状态
crawl_status = {"running": False, "progress": "", "total": 0, "done": 0, "match": 0}


# ============================================================
#  页面路由
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


# ============================================================
#  API 路由
# ============================================================

@app.route("/api/search")
def api_search():
    """搜索交易卡"""
    keyword = request.args.get("keyword", "").strip()
    max_results = int(request.args.get("max", 50))

    if not keyword:
        return jsonify({"error": "请输入关键词"}), 400

    try:
        results = search_trading_cards(keyword, max_results=max_results)
        return jsonify({
            "success": True,
            "keyword": keyword,
            "count": len(results),
            "results": results,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/data")
def api_data():
    """获取已保存的卡片数据"""
    data_file = os.path.join(DATA_DIR, "trading_cards.json")
    if not os.path.exists(data_file):
        return jsonify({"success": True, "cards": [], "count": 0})

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            cards = json.load(f)
        return jsonify({
            "success": True,
            "count": len(cards),
            "cards": cards,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/delete", methods=["POST"])
def api_data_delete():
    """删除指定卡片数据"""
    data = request.get_json()
    card_ids = data.get("card_ids", [])

    if not card_ids:
        return jsonify({"error": "请提供要删除的卡片 ID"}), 400

    data_file = os.path.join(DATA_DIR, "trading_cards.json")
    if not os.path.exists(data_file):
        return jsonify({"success": True, "deleted": 0, "message": "暂无数据"})

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            cards = json.load(f)

        id_set = set(card_ids)
        before = len(cards)
        cards = [c for c in cards if c.get("id") not in id_set]
        deleted = before - len(cards)

        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False, indent=2)

        return jsonify({
            "success": True,
            "deleted": deleted,
            "remaining": len(cards),
            "message": f"已删除 {deleted} 张卡片" if deleted else "未找到匹配的卡片",
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/search-results")
def api_search_results():
    """获取最后一次搜索结果"""
    data_file = os.path.join(DATA_DIR, "search_results.json")
    if not os.path.exists(data_file):
        return jsonify({"success": True, "results": [], "count": 0})

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            results = json.load(f)
        return jsonify({
            "success": True,
            "count": len(results),
            "results": results,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/crawl", methods=["POST"])
def api_crawl():
    """爬取指定卡片的详细数据（异步）"""
    if crawl_status["running"]:
        return jsonify({"error": "爬取任务正在运行中，请等待完成"}), 400

    data = request.get_json()
    card_ids = data.get("card_ids", [])

    if not card_ids:
        return jsonify({"error": "请提供要爬取的卡片 ID"}), 400

    # 启动后台线程
    thread = threading.Thread(target=_do_crawl, args=(card_ids,), daemon=True)
    thread.start()

    return jsonify({
        "success": True,
        "message": f"开始爬取 {len(card_ids)} 张卡片",
        "total": len(card_ids),
    })


@app.route("/api/crawl/status")
def api_crawl_status():
    """获取爬取状态"""
    return jsonify(crawl_status)


@app.route("/api/stats")
def api_stats():
    """获取数据统计"""
    data_file = os.path.join(DATA_DIR, "trading_cards.json")
    if not os.path.exists(data_file):
        return jsonify({"success": True, "total_cards": 0, "brands": {}, "price_range": {}})

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            cards = json.load(f)

        # 品牌统计
        brands = {}
        for c in cards:
            b = c.get("brand", "Unknown")
            brands[b] = brands.get(b, 0) + 1

        # 价格统计
        prices = [c.get("min_price") for c in cards if isinstance(c.get("min_price"), (int, float))]

        return jsonify({
            "success": True,
            "total_cards": len(cards),
            "brands": dict(sorted(brands.items(), key=lambda x: -x[1])),
            "price_range": {
                "min": min(prices) if prices else None,
                "max": max(prices) if prices else None,
                "avg": round(sum(prices) / len(prices), 2) if prices else None,
            } if prices else {},
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
#  后台爬取
# ============================================================

def _do_crawl(card_ids):
    """后台爬取卡片详情"""
    global crawl_status
    crawl_status["running"] = True
    crawl_status["total"] = len(card_ids)
    crawl_status["done"] = 0
    crawl_status["match"] = 0
    crawl_status["progress"] = "初始化..."

    try:
        scraper = CardScraper(delay=0.8, output_dir=DATA_DIR)
        new_cards = []

        for i, cid in enumerate(card_ids):
            if not crawl_status["running"]:
                break

            crawl_status["done"] = i
            crawl_status["progress"] = f"正在爬取 [{i+1}/{len(card_ids)}] ID={cid}"

            url = f"https://snkrdunk.com/en/trading-cards/{cid}"
            data = scraper.scrape_card(url)

            if data:
                crawl_status["match"] += 1
                new_cards.append(data)

            time.sleep(0.8)

        # 合并保存结果
        data_file = os.path.join(DATA_DIR, "trading_cards.json")
        all_cards = []
        if os.path.exists(data_file):
            with open(data_file, "r", encoding="utf-8") as f:
                all_cards = json.load(f)

        # 按 ID 去重合并（新数据覆盖旧数据）
        existing_ids = {c["id"] for c in all_cards if "id" in c}
        for nc in new_cards:
            if nc.get("id") in existing_ids:
                # 替换已有
                for i, ec in enumerate(all_cards):
                    if ec.get("id") == nc["id"]:
                        all_cards[i] = nc
                        break
            else:
                all_cards.append(nc)

        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(all_cards, f, ensure_ascii=False, indent=2)

        crawl_status["progress"] = f"爬取完成！新增/更新 {len(new_cards)} 张卡片"

    except Exception as e:
        crawl_status["progress"] = f"错误: {e}"
    finally:
        crawl_status["running"] = False


# ============================================================
#  启动
# ============================================================

if __name__ == "__main__":
    print(f"启动 Web UI: http://127.0.0.1:5000")
    print(f"数据目录: {DATA_DIR}")
    app.run(debug=False, host="127.0.0.1", port=5000)
