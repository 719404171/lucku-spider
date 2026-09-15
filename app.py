"""
SNKRDUNK Trading Card Web UI - Flask 后端
提供搜索、爬取、数据展示的 Web 界面
"""
import functools
import json
import os
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.search_api import search_trading_cards, fetch_condition_prices, fetch_product_detail, fetch_card_detail, condition_effective_price

# MySQL 导入功能（可选依赖）
try:
    from scraper.database import import_cards, ensure_table, get_all_imported_ids, get_all_imported_cards, update_card_conditions, delete_card_by_crawler_id, delete_card_by_row_id, set_card_is_update, get_card_recycle_percent, get_card_sell_percent, update_card_price_by_crawler_id, update_product_price_by_crawler_id, db_load_settings, db_save_setting, debug_table_structure
    HAS_MYSQL = True
except ImportError:
    import_cards = ensure_table = get_all_imported_ids = get_all_imported_cards = update_card_conditions = delete_card_by_crawler_id = delete_card_by_row_id = set_card_is_update = get_card_recycle_percent = get_card_sell_percent = update_card_price_by_crawler_id = update_product_price_by_crawler_id = db_load_settings = db_save_setting = debug_table_structure = None
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
#  汇率（JPY -> HKD，存入 fx_rate 表；每次查询自动抓新汇率，
#  抓不到就用数据库最新汇率）
# ============================================================
def get_fx_rate() -> dict:
    """返回汇率信息：优先接口新值并已入库；失败用库内最新"""
    from scraper import fx as _fxmod
    info = _fxmod.get_hkd_rate(refresh=True)
    if not info:
        return {"rate": None, "source": "", "fetched_at": ""}
    return dict(info)


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


@app.route("/api/rate")
@api_login_required
def api_rate():
    """返回 JPY→HKD 汇率与来源时间（优先接口新汇率并已入库，失败用库内最新）"""
    info = get_fx_rate()
    return jsonify({
        "success": info.get("rate") is not None,
        "base": "JPY",
        "quote": "HKD",
        "rate": info.get("rate"),
        "source": info.get("source", ""),
        "fetched_at": info.get("fetched_at", ""),
    })


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
    """搜索交易卡（新站 snkrdunk.com/search，固定枚数 = 1枚）"""
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
            return jsonify({"error": f"无法连接 MySQL 服务器，请检查网络和防火墙。错误: {e}"}), 500
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
    """获取指定卡片的详情与各状态价格（来源 https://snkrdunk.com/apparels/{id}，价格已换港币）。
    可选 ?catalog={productCatalogId}：已知 catalog 时详情页与交易履历并行抓取，加载更快。"""
    try:
        catalog = request.args.get("catalog") or None
        detail = fetch_card_detail(card_id, catalog_id=catalog)
        if detail is None:
            return jsonify({"error": f"抓取详情失败（ID={card_id}），请确认该商品存在"}), 502
        return jsonify({"success": True, **detail})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/search-details", methods=["POST"])
@api_login_required
def api_search_details():
    """批量抓取搜索结果里多张卡片的详情/成色价格（服务端并发，结果按 id 返回）。

    Body: {"items": [{"id": "730968", "catalog_id": "844057"}, ...]}
    已知 catalog_id 的卡片，其详情页与交易履历会并行抓取。
    """
    data = request.get_json() or {}
    items = data.get("items") or []
    if not items:
        return jsonify({"error": "缺少 items"}), 400

    def _one(item):
        cid = str(item.get("id") or "").strip()
        if not cid:
            return cid, None
        catalog = item.get("catalog_id") or None
        try:
            detail = fetch_card_detail(cid, timeout=15, catalog_id=catalog)
            return cid, detail
        except Exception as e:
            print(f"[SEARCH-DETAILS] {cid} 失败: {e}")
            return cid, None

    details = {}
    with ThreadPoolExecutor(max_workers=min(6, max(1, len(items)))) as pool:
        for cid, detail in pool.map(_one, items):
            if detail is not None:
                details[cid] = detail

    return jsonify({"success": True, "count": len(details), "details": details})


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
        db_cards = get_all_imported_cards(only_update=False)

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
        # 每次爬取任务开始前抓取一次最新汇率（JPY→HKD）并写库
        try:
            from scraper import fx as _fxmod
            _fxmod.get_hkd_rate(refresh=True)
        except Exception:
            pass
        new_cards = []

        for i, cid in enumerate(card_ids):
            if not crawl_status["running"]:
                break

            crawl_status["done"] = i
            crawl_status["progress"] = f"正在爬取 [{i+1}/{len(card_ids)}] ID={cid}"

            data = fetch_product_detail(cid)

            if data:
                crawl_status["match"] += 1
                # 使用前端传入的状态价格（如有）
                if conditions_map and cid in conditions_map:
                    cond = conditions_map[cid]
                    if cond.get("all_prices"):
                        data["condition_prices"] = cond["all_prices"]
                    selected_grade = cond.get("selected")
                    if selected_grade and cond.get("all_prices"):
                        cp = cond["all_prices"].get(selected_grade, {}) or {}
                        # 存所选成色「chip 显示的港币价」= 最新已售优先，无成交退回在售价
                        eff_price, eff_format = condition_effective_price(cp)
                        if eff_price is not None:
                            data["deal_price"] = eff_price
                            data["deal_format"] = eff_format or f"${eff_price:.2f}"
                            data["deal_condition"] = selected_grade
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

        # 直接追加，不做去重（同一张卡可多次爬取）
        for nc in new_cards:
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
#  自动更新价格（定时任务）
# ============================================================

SETTINGS_FILE = os.path.join(DATA_DIR, "auto_update_settings.json")

_default_settings = {
    "enabled": False,
    "time1": "08:00",
    "time2": "20:00",
}

def _load_settings():
    if HAS_MYSQL:
        try:
            db_raw = db_load_settings()
            return {
                "enabled": db_raw.get("auto_update_enabled", False),
                "time1": db_raw.get("auto_update_time1", "08:00"),
                "time2": db_raw.get("auto_update_time2", "20:00"),
            }
        except Exception:
            pass
    # 回退到 JSON 文件
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(_default_settings)

def _save_settings(s):
    if HAS_MYSQL:
        try:
            db_save_setting("auto_update_enabled", s.get("enabled", False))
            db_save_setting("auto_update_time1", s.get("time1", "08:00"))
            db_save_setting("auto_update_time2", s.get("time2", "20:00"))
        except Exception:
            pass
    # 同时写入 JSON 文件作为备份
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

def _run_price_update():
    """执行一次价格更新：遍历数据库卡片，刷新 condition_prices 和 min_price"""
    result = {"success": 0, "fail": 0, "total": 0, "skip": 0, "details": []}
    if not HAS_MYSQL:
        print("[AUTO_UPDATE] MySQL 不可用，跳过")
        result["skip"] = 1
        return result

    from scraper.search_api import fetch_condition_prices
    # 每次自动更新前抓取一次最新汇率（JPY→HKD）并写库，失败则用库内最新
    try:
        from scraper import fx as _fxmod
        _fxmod.get_hkd_rate(refresh=True)
    except Exception:
        pass
    cards = get_all_imported_cards()
    # 按 id 去重
    seen = set()
    unique = []
    for c in cards:
        if c["id"] not in seen:
            seen.add(c["id"])
            unique.append(c)

    result["total"] = len(unique)
    print(f"[AUTO_UPDATE] 开始更新 {result['total']} 张卡片价格...")

    # 读取回收和售卖百分比
    recycle_percent = 0
    sell_percent = 0
    try:
        recycle_percent = get_card_recycle_percent() if 'get_card_recycle_percent' in dir() else 0
    except Exception:
        pass
    try:
        sell_percent = get_card_sell_percent() if 'get_card_sell_percent' in dir() else 0
    except Exception:
        pass
    if not recycle_percent:
        try:
            from scraper.database import get_card_recycle_percent
            recycle_percent = get_card_recycle_percent()
        except Exception:
            pass
    if not sell_percent:
        try:
            from scraper.database import get_card_sell_percent
            sell_percent = get_card_sell_percent()
        except Exception:
            pass
    print(f"[AUTO_UPDATE] 卡牌回收百分比: {recycle_percent}%, 售卖百分比: {sell_percent}%")

    for i, card in enumerate(unique):
        cid = card["id"]
        try:
            prices = fetch_condition_prices(cid, timeout=8, fresh=True)
            if prices:
                # 有效成交价 = 最新已售(1枚)优先，无已售记录退回当前在售价
                eff = {}
                for g, v in prices.items():
                    if not v:
                        continue
                    p, f = condition_effective_price(v)
                    if p is not None:
                        eff[g] = (float(p), f or f"${float(p):.2f}")
                if not eff:
                    result["fail"] += 1
                    continue

                min_price = min(p for p, _ in eff.values())

                old_condition = card.get("deal_condition")
                deal_condition = old_condition if (old_condition and old_condition in eff) else None
                if not deal_condition:
                    # 原成色已无有效价时，自动改用最低有效价成色
                    deal_condition = min(eff, key=lambda g: eff[g][0])
                deal_price, deal_format = eff[deal_condition]

                updated = update_card_conditions(
                    cid, min_price, prices,
                    deal_condition=deal_condition,
                    deal_price=deal_price,
                    deal_format=deal_format,
                )
                if updated:
                    result["success"] += 1
                else:
                    result["fail"] += 1

                # 同步更新 card 表的 card_price
                if deal_price is not None and recycle_percent > 0:
                    try:
                        from scraper.database import update_card_price_by_crawler_id
                        update_card_price_by_crawler_id(cid, deal_price, recycle_percent)
                    except Exception:
                        pass

                # 同步更新 product 表的 product_price
                if deal_price is not None and sell_percent > 0:
                    try:
                        from scraper.database import update_product_price_by_crawler_id
                        update_product_price_by_crawler_id(cid, deal_price, sell_percent)
                    except Exception:
                        pass
            else:
                result["fail"] += 1
        except Exception as e:
            result["fail"] += 1
            print(f"[AUTO_UPDATE] [{cid}] 失败: {e}")

        if (i + 1) % 10 == 0:
            print(f"[AUTO_UPDATE] 进度 {i+1}/{result['total']}")

    print(f"[AUTO_UPDATE] 完成！成功 {result['success']}，失败 {result['fail']}，共 {result['total']} 张")
    return result


def _scheduler_loop():
    """后台线程：每分钟检查一次是否需要执行定时更新"""
    import time as _time
    _time.sleep(10)  # 等服务器启动
    last_run_date = ""
    while True:
        try:
            settings = _load_settings()
            if settings.get("enabled"):
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                time_str = now.strftime("%H:%M")
                t1 = settings.get("time1", "08:00")
                t2 = settings.get("time2", "20:00")

                # 每天每个时间点只执行一次
                run_key = f"{today}_{time_str}"
                if (time_str == t1 or time_str == t2) and run_key != last_run_date:
                    last_run_date = run_key
                    print(f"[AUTO_UPDATE] 定时触发 {time_str}")
                    try:
                        _run_price_update()
                    except Exception as e:
                        print(f"[AUTO_UPDATE] 执行失败: {e}")
        except Exception:
            pass
        _time.sleep(60)


# 启动后台调度线程
scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
scheduler_thread.start()


# ============================================================
#  API — 自动更新设置
# ============================================================

@app.route("/api/settings/auto-update", methods=["GET"])
@api_login_required
def api_get_auto_update_settings():
    return jsonify({"success": True, "settings": _load_settings()})


@app.route("/api/settings/auto-update", methods=["POST"])
@api_login_required
def api_set_auto_update_settings():
    data = request.get_json()
    if not data:
        return jsonify({"error": "无效参数"}), 400
    settings = _load_settings()
    if "enabled" in data:
        settings["enabled"] = bool(data["enabled"])
    if "time1" in data:
        settings["time1"] = str(data["time1"])
    if "time2" in data:
        settings["time2"] = str(data["time2"])
    _save_settings(settings)
    return jsonify({"success": True, "settings": settings})


@app.route("/api/auto-update/run-now", methods=["POST"])
@api_login_required
def api_run_auto_update_now():
    """手动触发一次价格更新（同步执行，返回完整结果）"""
    try:
        result = _run_price_update()
        return jsonify({
            "success": True,
            "total": result["total"],
            "updated": result["success"],
            "failed": result["fail"],
            "message": f"更新完成：成功 {result['success']} 张，失败 {result['fail']} 张，共 {result['total']} 张"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/stats/delete", methods=["POST"])
@api_login_required
def api_stats_delete():
    """从数据库删除指定 crawler_id 的卡片记录"""
    if not HAS_MYSQL:
        return jsonify({"error": "MySQL 不可用"}), 400

    data = request.get_json()
    card_id = data.get("card_id", "")
    if not card_id:
        return jsonify({"error": "请提供 card_id"}), 400

    try:
        deleted = delete_card_by_crawler_id(card_id)
        if deleted:
            return jsonify({"success": True, "message": f"已删除 {card_id}"})
        else:
            return jsonify({"success": False, "message": "未找到匹配记录"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats/delete-row", methods=["POST"])
@api_login_required
def api_stats_delete_row():
    """根据 MySQL 自增 id 删除单条记录"""
    if not HAS_MYSQL:
        return jsonify({"error": "MySQL 不可用"}), 400

    data = request.get_json()
    row_id = data.get("row_id")
    if not row_id:
        return jsonify({"error": "请提供 row_id"}), 400

    try:
        deleted = delete_card_by_row_id(int(row_id))
        if deleted:
            return jsonify({"success": True, "message": f"已删除 ID={row_id}"})
        else:
            return jsonify({"success": False, "message": "未找到匹配记录"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats/toggle-update", methods=["POST"])
@api_login_required
def api_stats_toggle_update():
    """切换卡片的 is_update 状态"""
    if not HAS_MYSQL:
        return jsonify({"error": "MySQL 不可用"}), 400

    data = request.get_json()
    card_id = data.get("card_id", "")
    is_update = data.get("is_update", True)
    if not card_id:
        return jsonify({"error": "请提供 card_id"}), 400

    try:
        ok = set_card_is_update(card_id, bool(is_update))
        if ok:
            return jsonify({"success": True, "is_update": bool(is_update), "message": f"{'启用' if is_update else '关闭'}自动更新"})
        else:
            return jsonify({"success": False, "message": "未找到匹配记录"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stats/update-card", methods=["POST"])
@api_login_required
def api_stats_update_card():
    """手动更新单张卡片：即时抓取最新各成色价格并写库，同步重算回收/售价"""
    if not HAS_MYSQL:
        return jsonify({"error": "MySQL 不可用"}), 400

    data = request.get_json()
    card_id = str(data.get("card_id", "")).strip()
    if not card_id:
        return jsonify({"error": "请提供 card_id"}), 400

    try:
        # 抓取最新汇率（成功写库；失败用库内最新）
        try:
            from scraper import fx as _fxmod
            _fxmod.get_hkd_rate(refresh=True)
        except Exception:
            pass

        # 读取该 crawler_id 现有记录（保留原选中成色）
        existing = [x for x in get_all_imported_cards(only_update=False) if str(x.get("id", "")) == card_id]
        if not existing:
            return jsonify({"success": False, "error": f"数据库未找到 crawler_id={card_id} 的记录"}), 404
        old_condition = existing[0].get("deal_condition") or ""

        prices = fetch_condition_prices(card_id, timeout=15, fresh=True)
        if not prices:
            return jsonify({"success": False, "error": "抓取不到该卡片价格，可能已下架或无在售"}), 502

        # 有效成交价 = 最新已售(1枚)优先，无已售记录退回当前在售价
        eff = {}
        for g, v in prices.items():
            if not v:
                continue
            p, f = condition_effective_price(v)
            if p is not None:
                eff[g] = (float(p), f or f"${float(p):.2f}")
        if not eff:
            return jsonify({"success": False, "error": "抓取不到可用成交价/在售价"}), 502
        min_price = min(p for p, _ in eff.values())

        deal_condition = old_condition if (old_condition and old_condition in eff) else None
        if not deal_condition:
            # 原成色已无有效价时，自动改用当前最低有效价成色
            deal_condition = min(eff, key=lambda g: eff[g][0])
        deal_price, deal_format = eff[deal_condition]

        ok = update_card_conditions(
            card_id, min_price, prices,
            deal_condition=deal_condition,
            deal_price=deal_price,
            deal_format=deal_format,
        )
        if not ok:
            return jsonify({"success": False, "error": "写入数据库失败"}), 500

        # 同步 card_price / product_price（按已设定的百分比）
        recycle_percent = sell_percent = 0
        try:
            recycle_percent = get_card_recycle_percent()
        except Exception:
            pass
        try:
            sell_percent = get_card_sell_percent()
        except Exception:
            pass
        if deal_price is not None and recycle_percent > 0:
            try:
                update_card_price_by_crawler_id(card_id, deal_price, recycle_percent)
            except Exception:
                pass
        if deal_price is not None and sell_percent > 0:
            try:
                update_product_price_by_crawler_id(card_id, deal_price, sell_percent)
            except Exception:
                pass

        cond_txt = f"{deal_condition} {deal_format}" if deal_price is not None else "无有效价"
        return jsonify({"success": True,
                        "message": f"更新完成：{card_id} 现价 {cond_txt}（{len(eff)} 个成色有报价）"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
#  远程重启（给 systemd 服务用，延迟 1 秒执行让 HTTP 响应先返回）
# ============================================================

@app.route("/api/restart", methods=["POST"])
@api_login_required
def api_restart():
    """一键重启服务（systemd restart spidercard）"""
    service_name = os.getenv("SERVICE_NAME", "spidercard")

    def _do_restart():
        time.sleep(1)  # 等当前 HTTP 响应返回
        try:
            subprocess.run(
                ["systemctl", "restart", service_name],
                check=False,
                capture_output=True,
            )
        except Exception:
            pass

    threading.Thread(target=_do_restart, daemon=True).start()
    return jsonify({"success": True, "message": "服务即将重启，稍候 3-5 秒后自动刷新..."})


# ============================================================
#  启动
# ============================================================

if __name__ == "__main__":
    print(f"启动 Web UI: http://127.0.0.1:5000")
    print(f"数据目录: {DATA_DIR}")
    app.run(debug=False, host="127.0.0.1", port=5000)
