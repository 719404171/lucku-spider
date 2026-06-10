"""
Card Scraper - 爬取 SNKRDUNK 单个交易卡页面数据
从页面中嵌入的 Vue.js JSON 属性中提取结构化数据
"""

import csv
import html
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup


class CardScraper:
    """交易卡页面爬取器 - 从嵌入式 JSON 属性中提取数据"""

    def __init__(self, delay: float = 1.5, output_dir: str = "data"):
        """
        Args:
            delay: 请求之间的延迟（秒）
            output_dir: 数据输出目录
        """
        self.delay = delay
        self.output_dir = output_dir
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def fetch_page(self, url: str) -> Optional[str]:
        """获取页面 HTML"""
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"[ERROR] Failed to fetch {url}: {e}")
            return None

    def extract_card_id(self, url: str) -> str:
        """从 URL 中提取卡片 ID"""
        match = re.search(r"/trading-cards/(\d+)", url)
        return match.group(1) if match else "unknown"

    @staticmethod
    def _find_vue_data(soup: BeautifulSoup, attr_name: str) -> Optional[dict]:
        """查找页面中指定 Vue 属性的 JSON 数据"""
        for elem in soup.find_all(True):
            val = elem.attrs.get(attr_name)
            if val:
                try:
                    return json.loads(html.unescape(val))
                except (json.JSONDecodeError, Exception) as e:
                    print(f"    [WARN] Failed to parse {attr_name}: {e}")
                    return None
        return None

    def parse_card_page(self, html_content: str, url: str) -> Optional[Dict]:
        """
        解析卡片页面 HTML，从嵌入式 JSON 属性中提取结构化数据。

        SNKRDUNK 使用 Vue.js，数据类型：
          <trading-card-detail>           - Box/Pack 产品
          <trading-card-single-detail>    - 单卡产品（含 :summary）
          <trading-card-single-listings>  - 二手列表页

        Returns:
            Dict with card data fields
        """
        soup = BeautifulSoup(html_content, "lxml")
        card_id = self.extract_card_id(url)

        # 从 <title> 获取标题
        title = ""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True).replace(" | SNKRDUNK", "").strip()

        # 从页面标题标签提取产品名称（meta og:title 比 h1 更可靠）
        og_title = soup.find("meta", property="og:title")
        page_title = og_title.get("content", title) if og_title else title

        # 识别页面类型：单卡详情 / 盒包详情 / 其他
        has_single_detail = bool(soup.find("trading-card-single-detail"))
        has_detail = bool(soup.find("trading-card-detail"))

        # --- 提取嵌入的 JSON 数据 ---
        trading_card_data = self._find_vue_data(soup, ":trading-card") or {}
        brand_data = self._find_vue_data(soup, ":brand") or {}
        category_data = self._find_vue_data(soup, ":category") or {}
        summary_data = self._find_vue_data(soup, ":summary") or {}

        # --- 品牌 ---
        brand_name = brand_data.get("name", "")

        # --- 品类 ---
        category_name = category_data.get("title", "") or category_data.get("name", "")

        # --- 卡名 ---
        card_name = trading_card_data.get("name", "") or page_title

        # --- 价格 ---
        min_price = trading_card_data.get("minPrice")
        min_price_currency = trading_card_data.get("minPriceCurrency", "")
        min_price_format = trading_card_data.get("minPriceFormat", "")

        # --- :summary 字段（仅单个单卡页面有） ---
        used_listing_count = summary_data.get("listingCount") or summary_data.get("usedListingCount")
        used_listing_count_text = summary_data.get("usedListingCountText", "")
        used_min_price = summary_data.get("usedMinPrice") or summary_data.get("usedMinPriceAmount")
        used_min_price_currency = summary_data.get("usedMinPriceCurrency", "")
        used_min_price_format = summary_data.get("usedMinPriceFormat", "")
        used_listing_count_formatted = summary_data.get("usedListingCountFormattedNum", "")
        # 新增: max_price
        max_price = summary_data.get("maxPrice") or summary_data.get("maxPriceAmount")
        max_price_amount = summary_data.get("maxPriceAmount")
        max_price_currency = summary_data.get("maxPriceCurrency", "")
        max_price_format = summary_data.get("maxPriceFormat", "")

        # --- :trading-card 字段 ---
        listing_count = trading_card_data.get("listingCount", 0)
        offer_count = trading_card_data.get("offerCount", 0)
        released_at = trading_card_data.get("releasedAt", "")
        product_code = trading_card_data.get("productNumber", "")
        thumbnail_url = trading_card_data.get("thumbnailUrl", "")

        # --- 判断卡片类型 ---
        if has_single_detail:
            card_type = "single"
        elif has_detail:
            card_type = "box_pack"
        else:
            card_type = "single"
        # 额外根据名称修正
        if not has_single_detail and (card_name and ("Box" in card_name or "Pack" in card_name)):
            card_type = "box_pack"

        # --- 图片 ---
        image_urls = []
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if src and "ibyteimg" in src and "favorite.svg" not in src:
                if src not in image_urls:
                    image_urls.append(src)

        # --- 描述 ---
        description = ""
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            description = meta_desc.get("content", "")

        # --- 从 dataLayer 获取额外数据 ---
        price_from_datalayer = None
        product_code_datalayer = None
        for script in soup.find_all("script"):
            if script.string and "dataLayer" in script.string:
                for match in re.finditer(r'dataLayer\.push\((\{.*?\})\)', script.string, re.DOTALL):
                    try:
                        dl_data = json.loads(match.group(1))
                        if dl_data.get("price") is not None:
                            price_from_datalayer = dl_data["price"]
                        if dl_data.get("product_code"):
                            product_code_datalayer = dl_data["product_code"]
                    except json.JSONDecodeError:
                        pass

        result: Dict[str, Any] = {
            "id": card_id,
            "url": url,
            "title": title,
            "card_name": card_name,
            "brand": brand_name,
            "category": category_name,
            "min_price": min_price,
            "min_price_currency": min_price_currency,
            "min_price_format": min_price_format,
            "listing_count": listing_count,
            "offer_count": offer_count,
            # :summary 数据
            "used_listing_count": used_listing_count,
            "used_listing_count_text": used_listing_count_text,
            "used_min_price": used_min_price,
            "used_min_price_currency": used_min_price_currency,
            "used_min_price_format": used_min_price_format,
            # max_price
            "max_price": max_price,
            "max_price_amount": max_price_amount,
            "max_price_currency": max_price_currency,
            "max_price_format": max_price_format,
            # 发布日期和产品编码
            "release_date": released_at,
            "product_code": product_code or product_code_datalayer,
            # 其他
            "thumbnail_url": thumbnail_url,
            "card_type": card_type,
            "description": description,
            "image_urls": image_urls,
            "image_count": len(image_urls),
        }

        return result

    # ====================================================================
    #  Listing (Condition) Scraper
    # ====================================================================

    def parse_listing_page(self, html_content: str, url: str) -> Optional[Dict]:
        """
        解析单个 listing 页面（/en/trading-cards/used/listings/{uid}）

        提取条件(Condition)、卖家信息等。
        """
        soup = BeautifulSoup(html_content, "lxml")
        listing_data = self._find_vue_data(soup, ":listing") or {}
        seller_data = self._find_vue_data(soup, ":seller") or {}

        if not listing_data:
            return None

        # 提取 listing ID
        listing_id_match = re.search(r"/listings/([\w-]+)", url)
        listing_id = listing_id_match.group(1) if listing_id_match else ""

        # 从 :listing 中提取字段
        condition = listing_data.get("condition", "")
        condition_description = listing_data.get("conditionDescription", "")
        price = listing_data.get("price", "")
        price_amount = listing_data.get("priceAmount")
        price_currency = listing_data.get("priceCurrency", "") or listing_data.get("currency", "")
        price_format = listing_data.get("priceFormat", "")
        seller_id = listing_data.get("sellerId", "")
        listing_status = listing_data.get("listingStatus", "")

        # 卖家信息
        seller_name = seller_data.get("name", "")
        seller_rating = seller_data.get("rating", "")
        seller_transactions = seller_data.get("transactionCount", "")
        seller_shipping_days = seller_data.get("averageShippingDays", "")

        return {
            "listing_id": listing_id,
            "url": url,
            "condition": condition,
            "condition_description": condition_description,
            "price": price,
            "price_amount": price_amount,
            "price_currency": price_currency,
            "price_format": price_format,
            "seller_id": seller_id,
            "seller_name": seller_name,
            "seller_rating": seller_rating,
            "seller_transactions": seller_transactions,
            "seller_shipping_days": seller_shipping_days,
            "listing_status": listing_status,
        }

    def scrape_listing(self, url: str) -> Optional[Dict]:
        """
        爬取单个 listing 页面获取 condition 数据

        Args:
            url: listing 页面 URL，如 /en/trading-cards/used/listings/{uid}

        Returns:
            listing 数据字典，含 condition, price 等
        """
        listing_id = re.search(r"/listings/([\w-]+)", url)
        lid = listing_id.group(1) if listing_id else "unknown"
        print(f"[INFO] Scraping listing {lid}")

        html_content = self.fetch_page(url)
        if not html_content:
            return None

        data = self.parse_listing_page(html_content, url)
        if data:
            cond = data.get("condition", "?")
            price = data.get("price", "?")
            print(f"  -> Condition: {cond} | Price: {price}")
        else:
            print(f"  -> Failed to parse listing")

        time.sleep(self.delay)
        return data

    def scrape_card_listings(self, card_id: str, max_listings: Optional[int] = None) -> List[Dict]:
        """
        爬取某个卡片的 listing 页面（/en/trading-cards/{id}/used）中的所有 listing，
        获取每个 listing 的 condition 和价格数据。

        注意：该页面的 listing 数据由 Vue.js 动态加载，HTML 中不可见。
        因此此方法会返回空列表，数据需要通过 API 获取（未实现）。

        Args:
            card_id: 卡片 ID
            max_listings: 最大数量

        Returns:
            空列表（数据动态加载，无法从 HTML 获取）
        """
        print(f"[WARN] Listings for card {card_id} are loaded dynamically via JavaScript.")
        print(f"[WARN] Cannot extract individual listing data from server-rendered HTML.")
        print(f"[WARN] Use scrape_listing() with a specific listing URL to get condition data.")
        return []

    # ====================================================================
    #  Batch methods
    # ====================================================================

    def scrape_card(self, url: str) -> Optional[Dict]:
        """
        爬取单个卡片页面

        Args:
            url: 卡片页面 URL

        Returns:
            卡片数据字典
        """
        card_id = self.extract_card_id(url)
        print(f"[INFO] Scraping card {card_id}: {url}")

        html_content = self.fetch_page(url)
        if not html_content:
            return None

        data = self.parse_card_page(html_content, url)
        if data:
            name = data.get("card_name", "") or data.get("title", "")
            price = data.get("min_price") or data.get("used_min_price", "")
            listings = data.get("used_listing_count", "")
            summary = f"${price}" if price else ""
            if listings:
                summary += f" ({listings} listings)" if summary else f"{listings} listings"
            print(f"  -> {name[:60]} | {summary}")
        else:
            print(f"  -> Failed to parse")

        time.sleep(self.delay)
        return data

    @staticmethod
    def _match_keywords(name: str, keywords: List[str]) -> bool:
        """检查名称是否匹配所有关键词（不区分大小写，AND 逻辑）"""
        if not keywords:
            return True
        name_lower = name.lower()
        return all(kw.lower() in name_lower for kw in keywords)

    def scrape_cards(
        self,
        urls: List[str],
        max_cards: Optional[int] = None,
        checkpoint_file: Optional[str] = None,
        save_interval: int = 0,
        base_filename: str = "trading_cards",
        keywords: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        批量爬取卡片（支持 checkpoint 断点续爬 + 定期自动保存）

        流程：
          1. 如果提供 checkpoint_file，加载已完成的 URL ID 集合，跳过已完成
          2. 每成功爬取一张卡片，写入 checkpoint（轻量）
          3. 每爬取 save_interval 张，自动保存中间结果到文件
          4. 中断后再次运行 --resume 会跳过已完成的

        Args:
            urls: 卡片 URL 列表
            max_cards: 最大爬取数量
            checkpoint_file: checkpoint 文件路径
            save_interval: 每爬取 N 张自动保存中间结果（0 = 仅结束时保存）
            base_filename: 自动保存的文件名前缀
            keywords: 关键词列表，卡片名称必须包含所有关键词（AND 逻辑）才保存

        Returns:
            卡片数据列表
        """
        if max_cards:
            urls = urls[:max_cards]

        # 加载已有 checkpoint
        completed_ids: set = set()
        if checkpoint_file and os.path.exists(checkpoint_file):
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                completed_ids = {line.strip() for line in f if line.strip()}
            skipped = 0
            filtered = []
            for u in urls:
                cid = self.extract_card_id(u)
                if cid not in completed_ids:
                    filtered.append(u)
                else:
                    skipped += 1
            if skipped:
                print(f"[INFO] Checkpoint 发现 {len(completed_ids)} 张已完成，跳过 {skipped} 张")
            urls = filtered

        total = len(urls)
        if total == 0:
            print("[INFO] 所有卡片已完成，无需继续爬取")
            return []

        if keywords:
            print(f"[INFO] 关键词过滤: {' & '.join(keywords)} (AND 逻辑，不区分大小写)")

        results: List[Dict] = []
        filtered_out = 0
        last_save_count = 0

        for i, url in enumerate(urls):
            print(f"\n[{i + 1}/{total}] ", end="")
            data = self.scrape_card(url)

            if data:
                name = data.get("card_name", "") or data.get("title", "")

                # 关键词过滤
                if keywords and not self._match_keywords(name, keywords):
                    print(f"  [SKIP] 不匹配关键词: {name[:60]}")
                    filtered_out += 1
                    # 不匹配的也写 checkpoint，避免下次重复检查
                    if checkpoint_file:
                        os.makedirs(os.path.dirname(checkpoint_file) or ".", exist_ok=True)
                        with open(checkpoint_file, "a", encoding="utf-8") as f:
                            f.write(data["id"] + "\n")
                    continue

                results.append(data)
                # 写入 checkpoint（每张都记录）
                if checkpoint_file:
                    os.makedirs(os.path.dirname(checkpoint_file) or ".", exist_ok=True)
                    with open(checkpoint_file, "a", encoding="utf-8") as f:
                        f.write(data["id"] + "\n")

            # 定期自动保存中间结果
            if save_interval > 0 and len(results) - last_save_count >= save_interval:
                self.save_results(results, f"{base_filename}.json")
                self.save_csv(results, f"{base_filename}.csv")
                last_save_count = len(results)
                print(f"\n[INFO] 已自动保存 {len(results)} 张卡片中间结果")
            elif save_interval > 0 and (i + 1) % 50 == 0:
                # 即使没有新匹配结果，也定期显示进度
                pass

        if filtered_out > 0:
            print(f"\n[INFO] 关键词过滤: 共跳过 {filtered_out} 张不匹配的卡片")

        return results

    def fetch_page_title(self, url: str) -> Optional[str]:
        """
        快速获取页面标题（只提取 <title> 标签，不做完整解析）
        比 scrape_card 快得多，适合关键词过滤
        """
        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            # 从 HTML 中提取 <title> 标签（不用 BeautifulSoup，更快）
            match = re.search(rb'<title[^>]*>(.*?)</title>', resp.content, re.IGNORECASE | re.DOTALL)
            if match:
                raw = match.group(1).decode('utf-8', errors='replace')
                return raw.replace(' | SNKRDUNK', '').strip()
            return None
        except requests.RequestException:
            return None

    def search_cards(
        self,
        urls: List[str],
        keywords: List[str],
        max_matches: int = 50,
        scan_limit: Optional[int] = None,
        reverse: bool = True,
        checkpoint_file: Optional[str] = None,
        fast_scan: bool = True,
    ) -> List[Dict]:
        """
        关键词搜索模式 - 从最新卡片开始扫描，找到匹配即停止

        优化策略:
          1. 反转 URL 列表（最新卡 ID 最大，排在 sitemap 末尾）
          2. 达到 max_matches 后提前停止
          3. 不匹配的写入 checkpoint 避免重复
          4. 快速扫描模式 (fast_scan=True): 先只检查 <title>，匹配再做完整爬取

        Args:
            urls: 所有卡片 URL 列表
            keywords: 关键词列表（AND 逻辑）
            max_matches: 找到 N 张匹配后停止
            scan_limit: 最多扫描 N 张（即使没找够也停止）
            reverse: 是否从最新卡片开始扫描
            checkpoint_file: checkpoint 文件路径
            fast_scan: 启用快速扫描（只检查标题，不解析完整页面，约快 3-5 倍）

        Returns:
            匹配的卡片数据列表
        """
        if not keywords:
            print("[ERROR] search_cards 需要指定 keywords")
            return []

        # 反转：最新卡（ID最大）排前面
        if reverse:
            # 按 URL 中的 ID 数字降序排列
            def _url_sort_key(u):
                m = re.search(r"/trading-cards/(\d+)", u)
                return -int(m.group(1)) if m else 0
            urls = sorted(urls, key=_url_sort_key)
            print(f"[INFO] 从最新卡片开始搜索 (共 {len(urls)} 张)")

        # 加载 checkpoint
        completed_ids: set = set()
        if checkpoint_file and os.path.exists(checkpoint_file):
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                completed_ids = {line.strip() for line in f if line.strip()}
            skipped = 0
            filtered = []
            for u in urls:
                cid = self.extract_card_id(u)
                if cid not in completed_ids:
                    filtered.append(u)
                else:
                    skipped += 1
            if skipped:
                print(f"[INFO] 跳过了 {skipped} 张已扫描过的卡片")
            urls = filtered

        if scan_limit:
            urls = urls[:scan_limit]

        total = len(urls)
        print(f"[INFO] 搜索关键词: {' & '.join(keywords)} (AND 逻辑)")
        print(f"[INFO] 目标: 找到 {max_matches} 张匹配即停止")
        print(f"[INFO] 本次将扫描: {total} 张卡片\n")

        if fast_scan:
            print(f"[INFO] 快速扫描模式启用 (约 0.3s/张，先检查标题再完整爬取)")

        results: List[Dict] = []
        scanned = 0

        for i, url in enumerate(urls):
            if len(results) >= max_matches:
                print(f"\n[INFO] 已找到 {len(results)} 张匹配卡片，停止扫描")
                break

            scanned += 1
            cid = self.extract_card_id(url)
            print(f"\r[{scanned}/{total}] ", end="")

            if fast_scan:
                # 快速模式：先只检查 <title>
                title = self.fetch_page_title(url)
                if title and self._match_keywords(title, keywords):
                    print(f"\r[{scanned}/{total}] title匹配，正在爬取详情...")
                    data = self.scrape_card(url)
                    if data:
                        results.append(data)
                        print(f"\r[{scanned}/{total}] [MATCH #{len(results)}/{max_matches}] {data.get('card_name','')[:60]}\n", end="")
                    else:
                        print(f"\r[{scanned}/{total}] [获取详情失败]\n", end="")
                else:
                    # 不匹配，只写 checkpoint
                    pass
            else:
                data = self.scrape_card(url)
                if data:
                    name = data.get("card_name", "") or data.get("title", "")
                    if self._match_keywords(name, keywords):
                        results.append(data)
                        print(f"\r[{scanned}/{total}] [MATCH #{len(results)}/{max_matches}] {name[:60]}\n", end="")

            # 都写 checkpoint
            if checkpoint_file:
                os.makedirs(os.path.dirname(checkpoint_file) or ".", exist_ok=True)
                with open(checkpoint_file, "a", encoding="utf-8") as f:
                    f.write(cid + "\n")

        print(f"\n[INFO] 搜索完成: 扫描 {scanned} 张, 匹配 {len(results)} 张")
        return results

    # ====================================================================
    #  Save methods
    # ====================================================================

    def save_results(self, results: List[Dict], filename: str = "trading_cards.json") -> str:
        """保存结果到 JSON 文件"""
        os.makedirs(self.output_dir, exist_ok=True)
        filepath = os.path.join(self.output_dir, filename)

        output_data = []
        for item in results:
            item_copy = item.copy()
            item_copy["image_count"] = len(item_copy.pop("image_urls", []))
            output_data.append(item_copy)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"\n[INFO] Saved {len(results)} cards to {filepath}")
        return filepath

    def save_csv(self, results: List[Dict], filename: str = "trading_cards.csv") -> str:
        """保存结果为 CSV 文件"""
        os.makedirs(self.output_dir, exist_ok=True)
        filepath = os.path.join(self.output_dir, filename)
        if not results:
            return filepath
        exclude_fields = {"image_urls"}
        fieldnames = [k for k in results[0].keys() if k not in exclude_fields]
        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in results:
                row = {k: v for k, v in item.items() if k not in exclude_fields}
                writer.writerow(row)
        print(f"[INFO] Saved {len(results)} cards to {filepath}")
        return filepath

    def save_listings_results(self, results: List[Dict], filename: str = "listings.json") -> str:
        """保存 listing 结果到 JSON"""
        os.makedirs(self.output_dir, exist_ok=True)
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[INFO] Saved {len(results)} listings to {filepath}")
        return filepath
