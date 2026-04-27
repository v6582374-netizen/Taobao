from __future__ import annotations

import re
from dataclasses import asdict
from html import unescape
from pathlib import Path
from typing import Any

from .models import Product, Review
from .products import extract_products_from_legacy_html, parse_detail_price
from .reviews import parse_review_candidate
from .utils import canonical_item_url, extract_item_id, now_iso, parse_sales, safe_text


def import_products_from_directory(config: dict[str, Any]) -> list[dict[str, Any]]:
    base_dir = Path(str(config.get("imports_dir", "imports"))) / "products"
    html_files = sorted(base_dir.glob("*.html"))
    limit = int(config.get("limit_products", 2))
    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    for html_file in html_files:
        page_products = extract_products_from_saved_html(html_file.read_text(encoding="utf-8", errors="ignore"))
        for item in page_products:
            item_id = safe_text(item.get("item_id"))
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            item["notes"] = _join_notes(safe_text(item.get("notes")), f"import_file={html_file.name}")
            products.append(item)
            if len(products) >= limit:
                return _to_ranked_product_dicts(products[:limit])
    return _to_ranked_product_dicts(products[:limit])


def extract_products_from_saved_html(html: str) -> list[dict[str, Any]]:
    legacy = extract_products_from_legacy_html(html)
    if legacy:
        for item in legacy:
            item["item_url"] = canonical_item_url(safe_text(item.get("item_url")))
        return legacy

    products: list[dict[str, Any]] = []
    seen: set[str] = set()
    anchor_pattern = re.compile(r"<a\b[^>]*href=[\"']([^\"']*item\.htm[^\"']*id=\d+[^\"']*)[\"'][^>]*>(.*?)</a>", re.I | re.S)
    for match in anchor_pattern.finditer(html):
        raw_url = unescape(match.group(1))
        item_url = canonical_item_url(raw_url)
        item_id = extract_item_id(item_url)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        start = match.start()
        end = min(len(html), match.end() + 1600)
        card_html = html[start:end]
        card_text = html_to_text(card_html)
        title = _extract_anchor_title(match.group(0), match.group(2)) or _guess_product_title(card_text)
        price = parse_detail_price(card_text) or _parse_yuan_price(card_text)
        products.append(
            {
                "item_id": item_id,
                "title": title,
                "price": price,
                "monthly_sales": _parse_card_sales(card_text),
                "shop_name": _guess_shop_name(card_text),
                "item_url": item_url,
                "notes": "" if price is not None else "price_parse_failed",
            }
        )
    return products


def import_reviews_from_directory(config: dict[str, Any], products: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    base_dir = Path(str(config.get("imports_dir", "imports"))) / "reviews"
    product_by_id = {safe_text(product.get("item_id")): product for product in products or []}
    target = int(config.get("reviews_per_product", 100))
    reviews: list[dict[str, Any]] = []
    for item_dir in sorted(path for path in base_dir.iterdir() if path.is_dir()) if base_dir.exists() else []:
        item_id = item_dir.name
        product = product_by_id.get(item_id, {"item_id": item_id, "title": ""})
        parsed_for_item: list[dict[str, Any]] = []
        seen_text: set[str] = set()
        for html_file in sorted(item_dir.glob("*.html")):
            html = html_file.read_text(encoding="utf-8", errors="ignore")
            for review in extract_reviews_from_saved_html(html, product, source_file=html_file.name):
                text = safe_text(review.get("comment_text"))
                if text and text not in seen_text:
                    seen_text.add(text)
                    parsed_for_item.append(review)
                if len(parsed_for_item) >= target:
                    break
            if len(parsed_for_item) >= target:
                break
        reviews.extend(parsed_for_item[:target])
        if not parsed_for_item:
            reviews.append(
                asdict(
                    Review(
                        item_id=item_id,
                        title=safe_text(product.get("title")),
                        comment_level="",
                        rating=None,
                        comment_time=now_iso(),
                        user_nickname="",
                        comment_text="",
                        sku_info="",
                        source="import_html",
                        crawl_status="failed",
                        failure_reason="no_reviews_from_imported_html",
                    )
                )
            )
    return reviews


def extract_reviews_from_saved_html(html: str, product: dict[str, Any], source_file: str = "") -> list[dict[str, Any]]:
    chunks = _review_html_chunks(html)
    if chunks:
        candidates = [html_to_text(chunk) for chunk in chunks]
    else:
        text = html_to_text(html)
        lines = [line for line in (safe_text(line) for line in text.splitlines()) if line]
        candidates = _candidate_windows(lines)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        parsed = parse_review_candidate({"text": candidate})
        if not parsed:
            continue
        comment_text = parsed["comment_text"]
        if comment_text in seen:
            continue
        seen.add(comment_text)
        rows.append(
            asdict(
                Review(
                    item_id=safe_text(product.get("item_id")),
                    title=safe_text(product.get("title")),
                    comment_level="未知",
                    rating=None,
                    comment_time=parsed["comment_time"],
                    user_nickname=parsed["user_nickname"],
                    comment_text=comment_text,
                    sku_info=parsed["sku_info"],
                    source=f"import_html:{source_file}" if source_file else "import_html",
                    crawl_status="ok",
                    failure_reason="",
                )
            )
        )
    return rows


def _review_html_chunks(html: str) -> list[str]:
    pattern = re.compile(
        r"<(?P<tag>section|article|li|div)\b[^>]*(?:review|comment|rate|evaluate)[^>]*>.*?</(?P=tag)>",
        re.I | re.S,
    )
    chunks = [match.group(0) for match in pattern.finditer(html)]
    return [chunk for chunk in chunks if "已购" in chunk or re.search(r"20\d{2}年\d{1,2}月\d{1,2}日", chunk)]


def html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript).*?</\1>", "\n", html)
    html = re.sub(r"(?i)<\s*(br|p|div|li|section|article|tr|td|span)\b[^>]*>", "\n", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    text = unescape(html)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text


def _candidate_windows(lines: list[str]) -> list[str]:
    candidates: list[str] = []
    for index, line in enumerate(lines):
        candidates.append(line)
        for size in (2, 3, 4, 5):
            window = " ".join(lines[index : index + size])
            if window and len(window) <= 1200:
                candidates.append(window)
    return candidates


def _to_ranked_product_dicts(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = now_iso()
    output: list[dict[str, Any]] = []
    for rank, item in enumerate(products, start=1):
        output.append(
            asdict(
                Product(
                    rank=rank,
                    item_id=safe_text(item.get("item_id")),
                    title=safe_text(item.get("title")),
                    price=item.get("price"),
                    monthly_sales=item.get("monthly_sales"),
                    shop_name=safe_text(item.get("shop_name")),
                    item_url=canonical_item_url(safe_text(item.get("item_url"))),
                    crawl_time=now,
                    notes=safe_text(item.get("notes")),
                )
            )
        )
    return output


def _extract_anchor_title(anchor_html: str, inner_html: str) -> str:
    title_match = re.search(r"\btitle=[\"']([^\"']+)[\"']", anchor_html, re.I | re.S)
    if title_match:
        return safe_text(unescape(title_match.group(1)))
    text = html_to_text(inner_html)
    if "￥" in text or len(text) < 4:
        return ""
    return safe_text(text)


def _guess_product_title(card_text: str) -> str:
    for line in (safe_text(line) for line in card_text.splitlines()):
        if len(line) >= 6 and "￥" not in line and not any(token in line for token in ("月销", "付款", "店", "券后", "优惠前")):
            return line
    return ""


def _parse_yuan_price(text: str) -> float | None:
    match = re.search(r"￥\s*(\d+(?:\.\d+)?)", safe_text(text).replace(",", ""))
    return float(match.group(1)) if match else None


def _parse_card_sales(text: str) -> int | None:
    match = re.search(r"(月销\s*\d+(?:\.\d+)?万?\+?|\d+(?:\.\d+)?万?\+?\s*人付款|已售\s*\d+(?:\.\d+)?万?\+?)", text)
    return parse_sales(match.group(1)) if match else None


def _guess_shop_name(text: str) -> str:
    for line in (safe_text(line) for line in text.splitlines()):
        if "店" in line and "￥" not in line and len(line) <= 40:
            return line
    return ""


def _join_notes(*parts: str) -> str:
    return "; ".join(part for part in parts if part)
