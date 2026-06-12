"""
SNKRDUNK Trading Card Web UI - Flask 后端
提供搜索、爬取、数据展示的 Web 界面
"""
import functools
import json
import os
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.search_api import search_trading_cards, print_search_results, fetch_condition_prices, CONDITION_MAP
from scraper.card_scraper import CardScraper
from scraper.sitemap_parser import discover_all_card_urls

# MySQL 导入功能（可选依赖）
try:
    from scraper.database import import_cards, ensure_table, get_all_imported_ids, get_all_imported_cards, debug_table_structure
    HAS_MYSQL = True
except ImportError:
    import_cards = ensure_table = get_all_imported_ids = debug_table_structure = None
    HAS_MYSQL = False
    print("[WARN] pymysql 未安装，MySQL 导入功能不可用。pip install pymysql")

app = Flask(__name__)
app.secret_key = "snkrdunk-secret-key-change-in-production"

# 默认登录账号 / 密码
AUTH_USER = "admin"
AUTH_PASS = "admin"

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 全局状态
crawl_status = {"running": False, "progress": "", "total": 0, "done": 0, "match": 0}


# ============================================================
#  登录校验装饰器
# ============================================================

def login_required(view):
    """需要登录才能访问的装饰器"""
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return view(**kwargs)
    return wrapped_view


def api_login_required(view):
    """API 登录校验装饰器（返回 401 json）"""
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if not session.get("logged_in"):
            return jsonify({"error": "未登录，请先登录"}), 401
        return view(**kwargs)
    return wrapped_view


# ============================================================
#  登录 / 登出
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login_page():
    """登录页面 + 登录提交"""
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == AUTH_USER and password == AUTH_PASS:
            session["logged_in"] = True
            session["username"] = username
            return redirect(url_for("index"))
        return render_template("login.html", error="账号或密码错误"), 401

    # 已经登录则直接跳转首页
    if session.get("logged_in"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


# ============================================================
#  页面路由
# ============================================================

@app.route("/")
@login_required
def index():
    return render_template("index.html")


# ============================================================
#  API 路由
# ============================================================

@app.route("/api/search")
@api_login_required
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
@api_login_required
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
@api_login_required
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


@app.route("/api/debug/table")
@api_login_required
def api_debug_table():
    """调试：查看 MySQL spider_cards 表结构"""
    if not HAS_MYSQL:
        return jsonify({"error": "pymysql 未安装"}), 500
    try:
        info = debug_table_structure()
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/data/import-mysql", methods=["POST"])
@api_login_required
def api_import_mysql():
    """将选中的卡片数据导入 MySQL 数据库"""
    data = request.get_json()
    card_ids = data.get("card_ids", [])

    if not card_ids:
        return jsonify({"error": "请选择要导入的卡片"}), 400

    data_file = os.path.join(DATA_DIR, "trading_cards.json")
    if not os.path.exists(data_file):
        return jsonify({"error": "暂无数据可导入"}), 400

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            all_cards = json.load(f)

        # 按 ID 过滤出用户选中的卡片
        id_set = set(card_ids)
        selected = [c for c in all_cards if c.get("id") in id_set]

        if not selected:
            return jsonify({"error": "未找到匹配的卡片数据"}), 400

        if not HAS_MYSQL:
            return jsonify({"error": "服务器未安装 pymysql，请执行: pip install pymysql"}), 500

        # 确保表存在
        ensure_table()

        # 调试日志
        try:
            tbl = debug_table_structure()
            print(f"[DEBUG] card 表结构: {len(tbl.get('columns',[]))} 字段, {tbl.get('row_count',0)} 行")
            print(f"[DEBUG] 字段列表: {tbl.get('columns', [])}")
        except Exception as e:
            print(f"[DEBUG] 查询表结构失败: {e}")

        print(f"[DEBUG] 准备导入 {len(selected)} 张卡片")
        for c in selected[:3]:
            print(f"[DEBUG] 示例数据: id={c.get('id')}, card_name={c.get('card_name','')[:20]}, min_price={c.get('min_price')}")

        # 分批导入（每批 50 张，避免连接超时）
        all_success_ids = []
        all_error_details = []

        batch_size = 50
        for i in range(0, len(selected), batch_size):
            batch = selected[i:i + batch_size]
            result = import_cards(batch)
            all_success_ids.extend(result["success_ids"])
            all_error_details.extend(result["errors"])

        # 从本地 JSON 删除已成功导入的数据
        if all_success_ids:
            success_set = set(all_success_ids)
            before = len(all_cards)
            all_cards = [c for c in all_cards if c.get("id") not in success_set]
            deleted = before - len(all_cards)
            print(f"[DEBUG] import-mysql: success_ids={all_success_ids}, before={before}, after={len(all_cards)}, deleted={deleted}")
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(all_cards, f, ensure_ascii=False, indent=2)

        total_imported = len(all_success_ids)
        total_errors = len(all_error_details)

        # 全部失败时返回错误，不清除数据
        if total_imported == 0 and total_errors > 0:
            first_errors = all_error_details[:3]
            return jsonify({
                "error": f"导入全部失败（{total_errors} 张），请检查数据格式。示例错误: {first_errors}"
            }), 500

        # 导入后验证
        verify_count = 0
        verify_error = None
        try:
            tbl = debug_table_structure()
            verify_count = tbl.get("row_count", 0)
            if tbl.get("error"):
                verify_error = tbl["error"]
        except Exception as e:
            verify_error = str(e)

        print(f"[DEBUG] 导入后验证: spider_cards 表共 {verify_count} 行")

        return jsonify({
            "success": True,
            "total": len(selected),
            "imported": total_imported,
            "failed": total_errors,
            "errors": all_error_details[:20],
            "verify_row_count": verify_count,
            "verify_error": verify_error,
            "message": f"导入完成: 成功 {total_imported} 张" +
                       (f"，失败 {total_errors} 张" if total_errors else "") +
                       (f"，spider_cards 表共 {verify_count} 行" if verify_count else ""),
        })
    except Exception as e:
        err_msg = str(e)
        # 区分 MySQL 连接错误和其他错误
        if "Can't connect" in err_msg or "Connection refused" in err_msg or "Timeout" in err_msg:
            return jsonify({"error": f"无法连接 MySQL 服务器 (8.210.90.110:3306)，请检查网络和防火墙。错误: {e}"}), 500
        return jsonify({"error": f"导入失败: {e}"}), 500


@app.route("/api/search-results")
@api_login_required
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


@app.route("/api/conditions/<card_id>")
@api_login_required
def api_condition_prices(card_id):
    """获取指定卡片的成色价格（A~I）"""
    try:
        # 检查是否有搜索结果中的缓存数据
        search_file = os.path.join(DATA_DIR, "search_results.json")
        card_data = None
        if os.path.exists(search_file):
            with open(search_file, "r", encoding="utf-8") as f:
                results = json.load(f)
                for r in results:
                    if str(r.get("id", "")) == str(card_id):
                        card_data = r
                        break

        prices = fetch_condition_prices(card_id, card_data)

        # 添加成色等级名称
        enriched = {}
        for cid, (grade, name) in CONDITION_MAP.items():
            cp = prices.get(grade, {"price": None, "format": "-", "count": 0})
            enriched[grade] = {
                **cp,
                "condition_id": cid,
                "condition_name": name,
            }

        return jsonify({"success": True, "card_id": card_id, "conditions": enriched})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/crawl", methods=["POST"])
@api_login_required
def api_crawl():
    """爬取指定卡片的详细数据（异步）"""
    if crawl_status["running"]:
        return jsonify({"error": "爬取任务正在运行中，请等待完成"}), 400

    data = request.get_json()
    card_ids = data.get("card_ids", [])
    conditions_map = data.get("conditions", {})  # {card_id: {grade: {price, count, ...}}} 从前端传入

    if not card_ids:
        return jsonify({"error": "请提供要爬取的卡片 ID"}), 400

    # 启动后台线程
    thread = threading.Thread(target=_do_crawl, args=(card_ids, conditions_map), daemon=True)
    thread.start()

    return jsonify({
        "success": True,
        "message": f"开始爬取 {len(card_ids)} 张卡片",
        "total": len(card_ids),
    })


@app.route("/api/crawl/status")
@api_login_required
def api_crawl_status():
    """获取爬取状态"""
    return jsonify(crawl_status)


@app.route("/api/stats")
@api_login_required
def api_stats():
    """获取数据统计 — 已导入数据从 MySQL 读取，未导入从 JSON 比对"""
    db_cards = []
    if HAS_MYSQL:
        db_cards = get_all_imported_cards()

    db_card_count = len(db_cards)

    # 从 JSON 文件获取未导入的卡片
    data_file = os.path.join(DATA_DIR, "trading_cards.json")
    if not os.path.exists(data_file):
        return jsonify({
            "success": True,
            "total_cards": db_card_count,
            "imported_count": db_card_count,
            "not_imported_count": 0,
            "imported_cards": db_cards,
            "not_imported_cards": [],
            "mysql_connected": HAS_MYSQL,
        })

    try:
        with open(data_file, "r", encoding="utf-8") as f:
            local_cards = json.load(f)

        # 已导入的 ID
        imported_ids = {c["id"] for c in db_cards if c.get("id")}

        # 未导入的卡片
        not_imported = []
        for c in local_cards:
            if str(c.get("id", "")) not in imported_ids:
                not_imported.append({
                    "id": c.get("id", ""),
                    "name": c.get("card_name", "?"),
                    "price": c.get("min_price"),
                })

        return jsonify({
            "success": True,
            "total_cards": db_card_count + len(not_imported),
            "imported_count": db_card_count,
            "not_imported_count": len(not_imported),
            "imported_cards": db_cards,
            "not_imported_cards": not_imported,
            "mysql_connected": HAS_MYSQL,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================
#  后台爬取
# ============================================================

def _do_crawl(card_ids, conditions_map=None):
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
                # 使用前端传入的成色价格
                if conditions_map and cid in conditions_map:
                    cond = conditions_map[cid]
                    # 保存所有成色价格
                    if "all_prices" in cond:
                        data["condition_prices"] = cond["all_prices"]
                    # 保存选中的成色价格
                    selected_grade = cond.get("selected")
                    if selected_grade and "all_prices" in cond:
                        cp = cond["all_prices"].get(selected_grade, {})
                        if cp.get("price") is not None:
                            data["deal_price"] = cp["price"]
                            data["deal_format"] = cp.get("format", f"${cp['price']:.2f}")
                new_cards.append(data)

            time.sleep(0.8)

        # 合并保存结果
        data_file = os.path.join(DATA_DIR, "trading_cards.json")
        all_cards = []
        if os.path.exists(data_file):
            with open(data_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    all_cards = json.loads(content)
                else:
                    all_cards = []
                    print(f"[WARN] {data_file} 为空，从空列表开始")

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
        import traceback
        tb = traceback.format_exc()
        crawl_status["progress"] = f"错误: {e}"
        print(f"[CRAWL ERROR] {tb}")
    finally:
        crawl_status["running"] = False


# ============================================================
#  启动
# ============================================================

if __name__ == "__main__":
    print(f"启动 Web UI: http://127.0.0.1:5000")
    print(f"数据目录: {DATA_DIR}")
    app.run(debug=False, host="127.0.0.1", port=5000)
