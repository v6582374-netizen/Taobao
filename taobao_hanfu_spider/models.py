from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Product:
    rank: int
    item_id: str
    title: str
    price: float | None
    monthly_sales: int | None
    shop_name: str
    item_url: str
    crawl_time: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Review:
    item_id: str
    title: str
    comment_level: str
    rating: float | None
    comment_time: str
    user_nickname: str
    comment_text: str
    sku_info: str
    source: str
    crawl_status: str
    failure_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

