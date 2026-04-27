from __future__ import annotations

import json
import re
from typing import Any

from .browser import BrowserSession, maybe_pause_for_verification
from .models import Product
from .utils import (
    canonical_item_url,
    extract_item_id,
    human_delay,
    normalize_url,
    now_iso,
    parse_price,
    parse_sales,
    safe_text,
    taobao_search_url,
)


PRODUCT_EVALUATE_JS = r"""
() => {
  const normalize = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const itemLinkSelector = 'a[href*="item.taobao.com/item.htm"], a[href*="detail.tmall.com/item.htm"], a[href*="item.htm?id="]';
  const findCard = (anchor) => {
    let node = anchor;
    for (let i = 0; i < 8 && node && node.parentElement; i += 1) {
      const text = normalize(node.innerText);
      const links = node.querySelectorAll ? node.querySelectorAll(itemLinkSelector).length : 0;
      if (links >= 1 && text.includes('¥') && /(付款|月销|已售|销量|人看过|券后|优惠前)/.test(text)) {
        return node;
      }
      node = node.parentElement;
    }
    return anchor.parentElement || anchor;
  };
  const titleFrom = (card, anchor) => {
    const titleNode = card.querySelector(
      '[class*="desc"] span, [class*="Desc"] span, [class*="title"], [class*="Title"], span[title], a[title]'
    );
    return normalize(titleNode ? (titleNode.innerText || titleNode.getAttribute('title')) : anchor.innerText);
  };
  const priceFrom = (card) => {
    const priceNode = card.querySelector('[class*="price"], [class*="Price"]');
    return normalize(priceNode ? priceNode.innerText : '');
  };
  const candidates = [];
  const anchors = Array.from(document.querySelectorAll(itemLinkSelector));
  const seen = new Set();
  for (const anchor of anchors) {
    const href = anchor.href || anchor.getAttribute('href') || '';
    const idMatch = href.match(/[?&]id=(\d+)/);
    if (!idMatch || seen.has(idMatch[1])) continue;
    const card = findCard(anchor);
    const text = normalize(card ? card.innerText : anchor.innerText);
    if (!text.includes('¥')) continue;
    seen.add(idMatch[1]);
    const shopNode = card && card.querySelector('[class*="shopName"], [class*="ShopName"], [class*="shopText"], [class*="shop"] [class*="Text"]');
    candidates.push({
      item_url: href,
      item_id: idMatch[1],
      title_text: titleFrom(card, anchor),
      price_text: priceFrom(card),
      shop_text: normalize(shopNode ? shopNode.innerText : ''),
      card_text: text
    });
  }
  return candidates;
}
"""

DETAIL_EVALUATE_JS = r"""
() => {
  const normalize = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const metaTitle = document.querySelector('meta[property="og:title"], meta[name="title"]');
  const titleNode = document.querySelector('h1, [class*="itemTitle"], [class*="ItemTitle"]');
  const rawTitle = metaTitle ? metaTitle.getAttribute('content') : (titleNode ? titleNode.innerText || titleNode.getAttribute('title') : document.title);
  return {
    title: normalize(rawTitle).replace(/[-_].*?(淘宝|天猫|tmall|taobao).*$/i, ''),
    body_text: normalize(document.body ? document.body.innerText : '')
  };
}
"""


def extract_products_from_legacy_html(html: str) -> list[dict[str, Any]]:
    match = re.search(r"g_page_config\s*=\s*(\{.*?\});", html, re.S)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    auctions = (
        payload.get("mods", {})
        .get("itemlist", {})
        .get("data", {})
        .get("auctions", [])
    )
    items: list[dict[str, Any]] = []
    for auction in auctions:
        item_url = canonical_item_url(str(auction.get("detail_url", "")))
        item_id = safe_text(auction.get("nid")) or extract_item_id(item_url)
        if not item_id:
            continue
        items.append(
            {
                "item_id": item_id,
                "title": safe_text(auction.get("raw_title") or auction.get("title")),
                "price": parse_price(auction.get("view_price")),
                "monthly_sales": parse_sales(auction.get("view_sales")),
                "shop_name": safe_text(auction.get("nick") or auction.get("shopName")),
                "item_url": item_url,
                "notes": "",
            }
        )
    return items


def _guess_title(raw: dict[str, Any]) -> str:
    title = safe_text(raw.get("title_text"))
    if title and "¥" not in title and len(title) > 3:
        return title
    lines = [line.strip() for line in safe_text(raw.get("card_text")).split(" ") if line.strip()]
    ignored = ("¥", "付款", "月销", "已售", "包邮", "退货", "天猫")
    for line in lines:
        if len(line) > 4 and not any(token in line for token in ignored):
            return line
    return title


def _guess_shop(raw: dict[str, Any]) -> str:
    shop = safe_text(raw.get("shop_text"))
    if shop:
        return shop
    text = safe_text(raw.get("card_text"))
    lines = [part.strip() for part in re.split(r"\s+", text) if part.strip()]
    for line in reversed(lines):
        if "店" in line and "¥" not in line:
            return line
    return ""


def _guess_sales(raw: dict[str, Any]) -> int | None:
    text = safe_text(raw.get("card_text"))
    for pattern in (
        r"(月销\s*\d+(?:\.\d+)?万?\+?)",
        r"(\d+(?:\.\d+)?万?\+?\s*人付款)",
        r"(已售\s*\d+(?:\.\d+)?万?\+?)",
        r"(销量\s*\d+(?:\.\d+)?万?\+?)",
    ):
        match = re.search(pattern, text)
        if match:
            return parse_sales(match.group(1))
    return None


def normalize_product_candidates(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_items:
        item_url = canonical_item_url(safe_text(raw.get("item_url")))
        item_id = safe_text(raw.get("item_id")) or extract_item_id(item_url)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        price = parse_price(raw.get("price") or raw.get("price_text") or raw.get("card_text"))
        products.append(
            {
                "item_id": item_id,
                "title": _guess_title(raw),
                "price": price,
                "monthly_sales": raw.get("monthly_sales") if raw.get("monthly_sales") is not None else _guess_sales(raw),
                "shop_name": _guess_shop(raw),
                "item_url": item_url,
                "notes": "" if price is not None else "price_parse_failed",
            }
        )
    return products


def parse_detail_price(text: str) -> float | None:
    text = safe_text(text).replace(",", "")
    if not text:
        return None
    label_patterns = (
        r"券后\s*￥?\s*(\d+(?:\.\d+)?)",
        r"券后价\s*￥?\s*(\d+(?:\.\d+)?)",
        r"到手价\s*￥?\s*(\d+(?:\.\d+)?)",
        r"优惠前\s*￥?\s*(\d+(?:\.\d+)?)",
        r"优惠价\s*￥?\s*(\d+(?:\.\d+)?)",
        r"现价\s*￥?\s*(\d+(?:\.\d+)?)",
        r"价格\s*￥?\s*(\d+(?:\.\d+)?)",
    )
    for pattern in label_patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))

    # Handle vertically separated labels from rendered pages: 券后 ￥ 68 优惠前 ￥ 78
    for label in ("券后", "券后价", "到手价", "优惠前", "优惠价"):
        index = text.find(label)
        if index >= 0:
            window = text[index : index + 80]
            match = re.search(r"￥\s*(\d+(?:\.\d+)?)", window)
            if match:
                return float(match.group(1))
    return None


class ProductCrawler:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def crawl(self) -> list[Product]:
        limit = int(self.config["limit_products"])
        keyword = str(self.config["keyword"])
        start_page = int(self.config.get("start_page", 1))
        end_page = self._resolve_end_page(start_page)
        products_per_page = int(self.config.get("products_per_page", limit))
        collected: list[dict[str, Any]] = []
        with BrowserSession(self.config) as session:
            page = session.new_page()
            if bool(self.config.get("manual_product_navigation", True)):
                page.goto("https://www.taobao.com", wait_until="domcontentloaded")
                if bool(self.config.get("auto_search_keyword", True)):
                    self._search_keyword_from_homepage(page, keyword)
                print(f"已打开淘宝并尝试搜索“{keyword}”。请确认已按销量排序，并准备采集第 1 页。")
            for page_number in range(start_page, end_page + 1):
                if len(collected) >= limit:
                    break
                if bool(self.config.get("manual_product_navigation", True)):
                    self._wait_for_manual_page(page, page_number, keyword)
                else:
                    url = taobao_search_url(keyword, page_number)
                    print(f"打开淘宝搜索第 {page_number} 页：{url}")
                    page.goto(url, wait_until="domcontentloaded")
                    maybe_pause_for_verification(page, f"搜索页第 {page_number} 页")
                    if bool(self.config.get("click_sales_sort", False)):
                        self._try_click_sales_sort(page)
                self._scroll_page(page)
                normalized = self._extract_current_page_products(page)
                page_items = [
                    dict(item, source_page=page_number)
                    for item in normalized
                    if not _has_product(collected, item)
                ]
                selected = page_items[: max(0, products_per_page)]
                print(f"第 {page_number} 页识别 {len(normalized)} 个候选，选取 {len(selected)} 个新商品。")
                collected.extend(selected)
                collected = _dedupe_products(collected)
                print(f"当前累计商品数：{len(collected)}/{limit}")
                human_delay(
                    float(self.config.get("min_delay_seconds", 2)),
                    float(self.config.get("max_delay_seconds", 6)),
                )
            if len(collected) < limit:
                print(f"已到达安全页数上限但仍未收满 {limit} 个商品，当前 {len(collected)} 个。可调大 max_product_pages 后重试。")

        now = now_iso()
        with BrowserSession(self.config) as session:
            detail_page = session.new_page()
            collected = [self._verify_product_detail(detail_page, item) for item in collected]
        output: list[Product] = []
        for index, item in enumerate(collected[:limit], start=1):
            output.append(
                Product(
                    rank=index,
                    item_id=str(item["item_id"]),
                    title=safe_text(item.get("title")),
                    price=item.get("price"),
                    monthly_sales=item.get("monthly_sales"),
                    shop_name=safe_text(item.get("shop_name")),
                    item_url=safe_text(item.get("item_url")),
                    crawl_time=now,
                    notes=_join_notes(safe_text(item.get("notes")), f"source_page={item.get('source_page', '')}"),
                )
            )
        return output

    def _resolve_end_page(self, start_page: int) -> int:
        configured_end = self.config.get("end_page")
        if configured_end not in (None, "", "null"):
            return int(configured_end)
        max_pages = max(1, int(self.config.get("max_product_pages", 10)))
        return start_page + max_pages - 1

    def _verify_product_detail(self, page, item: dict[str, Any]) -> dict[str, Any]:
        item = dict(item)
        item["item_url"] = canonical_item_url(safe_text(item.get("item_url")))
        if not item["item_url"]:
            return item
        try:
            page.goto(item["item_url"], wait_until="domcontentloaded")
            maybe_pause_for_verification(page, "商品详情页校验")
            page.wait_for_timeout(1500)
            detail = page.evaluate(DETAIL_EVALUATE_JS)
        except Exception as exc:
            item["notes"] = _join_notes(safe_text(item.get("notes")), f"detail_verify_failed={exc}")
            return item
        title = safe_text(detail.get("title"))
        if title:
            item["title"] = title
        detail_price = parse_detail_price(safe_text(detail.get("body_text")))
        if detail_price is not None:
            item["price"] = detail_price
            item["notes"] = _join_notes(safe_text(item.get("notes")), "price_from_detail")
        else:
            item["notes"] = _join_notes(safe_text(item.get("notes")), "price_from_search_fallback")
        return item

    def _wait_for_manual_page(self, page, page_number: int, keyword: str) -> None:
        print("")
        print(f"请在浏览器中手动停到淘宝搜索“{keyword}”的第 {page_number} 页，并确认已按销量排序。")
        print("如果当前页面显示 deny_h5、安全验证或登录页，请先在浏览器里处理到正常商品列表页面。")
        while True:
            input(f"页面准备好后按 Enter 采集第 {page_number} 页...")
            maybe_pause_for_verification(page, f"手动搜索页第 {page_number} 页")
            if bool(self.config.get("require_keyword_on_product_page", True)) and not self._page_matches_keyword(page, keyword):
                print(f"当前页面不像“{keyword}”搜索结果页，不采集。请手动搜索“{keyword}”后再继续。")
                continue
            if not self._is_punish_or_json_page(page):
                return
            print("当前仍像风控/JSON 拒绝页，不采集。请手动回到正常淘宝商品列表后再继续。")

    def _search_keyword_from_homepage(self, page, keyword: str) -> None:
        selectors = [
            'input[name="q"]',
            "input#q",
            'input[placeholder*="搜索"]',
            'input[type="text"]',
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count():
                    locator.fill(keyword, timeout=5000)
                    locator.press("Enter")
                    page.wait_for_load_state("domcontentloaded", timeout=10_000)
                    maybe_pause_for_verification(page, "淘宝首页关键词搜索")
                    return
            except Exception:
                continue
        print(f"没有自动定位到淘宝搜索框。请在浏览器里手动搜索“{keyword}”。")

    def _page_matches_keyword(self, page, keyword: str) -> bool:
        if keyword in safe_text(getattr(page, "url", "")):
            return True
        try:
            body_text = safe_text(page.locator("body").inner_text(timeout=3000))
        except Exception:
            return False
        return keyword in body_text

    def _extract_current_page_products(self, page) -> list[dict[str, Any]]:
        raw_items = page.evaluate(PRODUCT_EVALUATE_JS)
        normalized = normalize_product_candidates(raw_items)
        if normalized:
            return normalized
        html = ""
        try:
            html = page.content()
        except Exception:
            return []
        return extract_products_from_legacy_html(html)

    def _is_punish_or_json_page(self, page) -> bool:
        url = safe_text(getattr(page, "url", ""))
        body_text = ""
        try:
            body_text = safe_text(page.locator("body").inner_text(timeout=3000))
        except Exception:
            body_text = ""
        markers = (
            "deny_h5",
            "punish",
            "rgv587_flag",
            "安全验证",
            "访问被拒绝",
        )
        return any(marker in url or marker in body_text for marker in markers)

    def _try_click_sales_sort(self, page) -> None:
        for label in ("销量", "销售"):
            try:
                locator = page.get_by_text(label, exact=False).first
                if locator.count():
                    locator.click(timeout=2500)
                    page.wait_for_load_state("domcontentloaded", timeout=5000)
                    return
            except Exception:
                continue

    def _scroll_page(self, page) -> None:
        steps = max(0, int(self.config.get("scroll_steps", 1)))
        for _ in range(steps):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(800)
        if steps:
            page.mouse.wheel(0, -300)
            page.wait_for_timeout(500)


def _dedupe_products(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        item_id = safe_text(item.get("item_id"))
        if item_id and item_id not in seen:
            seen.add(item_id)
            output.append(item)
    return output


def _has_product(items: list[dict[str, Any]], candidate: dict[str, Any]) -> bool:
    candidate_id = safe_text(candidate.get("item_id"))
    return any(safe_text(item.get("item_id")) == candidate_id for item in items)


def _join_notes(*parts: str) -> str:
    return "; ".join(part for part in parts if part)
