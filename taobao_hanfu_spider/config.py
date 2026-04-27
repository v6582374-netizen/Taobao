from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_CONFIG: dict[str, Any] = {
    "keyword": "汉服",
    "limit_products": 100,
    "start_page": 1,
    "end_page": None,
    "max_product_pages": 10,
    "products_per_page": 50,
    "reviews_per_product": 100,
    "manual_product_navigation": True,
    "auto_search_keyword": True,
    "require_keyword_on_product_page": True,
    "click_sales_sort": False,
    "headless": False,
    "slow_mo_ms": 150,
    "timeout_ms": 30_000,
    "min_delay_seconds": 2,
    "max_delay_seconds": 6,
    "scroll_steps": 4,
    "review_page_only": True,
    "profile_dir": ".browser-profile",
    "data_dir": "data",
    "output_dir": "output",
    "products_excel": "hanfu_products.xlsx",
    "reviews_excel": "hanfu_reviews.xlsx",
    "price_bands": [
        {"name": "平价(<200)", "min": None, "max": 200.0},
        {"name": "中端(200-600)", "min": 200.0, "max": 600.0},
        {"name": "中高端(600-1500)", "min": 600.0, "max": 1500.0, "max_inclusive": True},
        {"name": "高端(>1500)", "min": 1500.0, "min_exclusive": True, "max": None},
    ],
}


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.lower() in {"true", "yes", "on"}:
        return True
    if value.lower() in {"false", "no", "off"}:
        return False
    if value.lower() in {"null", "none", "~"}:
        return None
    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def load_config(path: str | Path = "config.yaml") -> dict[str, Any]:
    """Load a tiny top-level YAML subset and merge it with defaults.

    This avoids requiring PyYAML for tests and exports. The shipped config only
    uses flat key/value pairs; nested defaults such as price bands stay in code.
    """

    config = dict(DEFAULT_CONFIG)
    file_path = Path(path)
    if not file_path.exists():
        return config

    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.split(" #", 1)[0].strip()
        if key:
            config[key] = _parse_scalar(value)
    return config


def data_path(config: dict[str, Any], filename: str) -> Path:
    path = Path(str(config["data_dir"]))
    path.mkdir(parents=True, exist_ok=True)
    return path / filename


def output_path(config: dict[str, Any], filename: str) -> Path:
    path = Path(str(config["output_dir"]))
    path.mkdir(parents=True, exist_ok=True)
    return path / filename
