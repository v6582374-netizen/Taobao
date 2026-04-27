from __future__ import annotations

from pathlib import Path
from typing import Any

from .xlsx import write_xlsx


PRODUCT_COLUMNS = [
    "rank",
    "item_id",
    "title",
    "price",
    "monthly_sales",
    "shop_name",
    "item_url",
    "crawl_time",
    "price_band",
    "band_ratio",
    "band_avg_price",
    "hot_price_band",
    "notes",
]

REVIEW_COLUMNS = [
    "item_id",
    "title",
    "comment_level",
    "rating",
    "comment_time",
    "user_nickname",
    "comment_text",
    "sku_info",
    "source",
    "crawl_status",
    "failure_reason",
    "matched_topics",
    "sentiment_label",
    "issue_tags",
    "top10_pain_point",
    "satisfaction_summary",
    "repurchase_barrier_reason",
]


def rows_from_dicts(items: list[dict[str, Any]], columns: list[str]) -> list[list[Any]]:
    return [columns] + [[item.get(column, "") for column in columns] for item in items]


def export_products(path: str | Path, products: list[dict[str, Any]], stats: list[dict[str, Any]]) -> None:
    stat_columns = ["price_band", "count", "ratio", "avg_price", "sales_sum", "is_hot_price_band"]
    write_xlsx(
        path,
        {
            "商品数据": rows_from_dicts(products, PRODUCT_COLUMNS),
            "价格带统计": rows_from_dicts(stats, stat_columns),
        },
    )


def export_reviews(path: str | Path, reviews: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    summary_rows = [
        ["metric", "value"],
        ["satisfaction_ratio", summary.get("satisfaction_ratio", 0)],
        ["satisfaction_summary", summary.get("satisfaction_summary", "")],
        ["repurchase_barrier_reason", summary.get("repurchase_barrier_reason", "")],
        ["", ""],
        ["pain_point", "count"],
    ]
    for row in summary.get("top_pain_points", []):
        summary_rows.append([row.get("pain_point"), row.get("count")])
    summary_rows.extend([["", ""], ["topic", "count"]])
    for row in summary.get("topic_summary", []):
        summary_rows.append([row.get("topic"), row.get("count")])
    summary_rows.extend([["", ""], ["high_frequency_term", "count"]])
    for row in summary.get("high_frequency_terms", []):
        summary_rows.append([row.get("term"), row.get("count")])
    write_xlsx(
        path,
        {
            "评论数据": rows_from_dicts(reviews, REVIEW_COLUMNS),
            "舆情汇总": summary_rows,
        },
    )
