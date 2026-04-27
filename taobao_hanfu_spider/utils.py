from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def human_delay(min_seconds: float, max_seconds: float) -> None:
    if max_seconds <= 0:
        return
    time.sleep(random.uniform(max(0, min_seconds), max(min_seconds, max_seconds)))


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_price(value: Any) -> float | None:
    text = safe_text(value)
    if not text:
        return None
    text = text.replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return float(match.group(1))


def parse_sales(value: Any) -> int | None:
    text = safe_text(value)
    if not text:
        return None
    text = text.replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)(万)?\+?", text)
    if not match:
        return None
    number = float(match.group(1))
    if match.group(2):
        number *= 10_000
    return int(number)


def normalize_url(url: str) -> str:
    url = safe_text(url)
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://www.taobao.com" + url
    return url


def canonical_item_url(url: str) -> str:
    url = normalize_url(url)
    item_id = extract_item_id(url)
    if not item_id:
        return url
    parsed = urlparse(url)
    host = parsed.netloc or "item.taobao.com"
    if "tmall.com" in host:
        host = "detail.tmall.com"
    else:
        host = "item.taobao.com"
    path = parsed.path if parsed.path and parsed.path.endswith("item.htm") else "/item.htm"
    return urlunparse(("https", host, path, "", urlencode({"id": item_id}), ""))


def extract_item_id(url_or_text: str) -> str:
    text = unquote(safe_text(url_or_text))
    parsed = urlparse(text)
    params = parse_qs(parsed.query)
    for key in ("id", "itemId", "item_id"):
        if params.get(key):
            return params[key][0]
    match = re.search(r"(?:id|itemId|item_id)[=:](\d+)", text)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d{8,})\b", text)
    return match.group(1) if match else ""


def taobao_search_url(keyword: str, page: int = 1) -> str:
    # Taobao search may honor either page or the result offset (`s`) depending
    # on the active frontend version, so include both when jumping pages.
    offset = max(0, page - 1) * 44
    return f"https://s.taobao.com/search?q={quote(keyword)}&sort=sale-desc&page={page}&s={offset}"


def read_json(path: str | Path, default: Any = None) -> Any:
    file_path = Path(path)
    if not file_path.exists():
        return default
    return json.loads(file_path.read_text(encoding="utf-8"))


def write_json(path: str | Path, data: Any) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def dedupe_by(items: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        value = safe_text(item.get(key))
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(item)
    return output
