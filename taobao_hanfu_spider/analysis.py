from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from .utils import parse_price, safe_text


TOPIC_KEYWORDS: dict[str, list[str]] = {
    "版型": ["版型", "显瘦", "上身", "款式", "形制", "裙摆", "腰身", "设计"],
    "色差": ["色差", "颜色", "图片不符", "偏色", "实物", "显黑", "褪色"],
    "做工": ["做工", "线头", "走线", "缝", "开线", "掉扣", "瑕疵", "质量"],
    "发货": ["发货", "物流", "快递", "配送", "到货", "催", "慢", "延迟"],
    "尺码": ["尺码", "码数", "大小", "偏大", "偏小", "合身", "腰围", "胸围"],
    "面料": ["面料", "布料", "材质", "棉", "纱", "雪纺", "透", "扎", "厚", "薄"],
    "售后": ["售后", "客服", "退货", "换货", "退款", "补发", "态度", "沟通"],
}

NEGATIVE_WORDS = [
    "差",
    "不好",
    "失望",
    "难看",
    "不值",
    "粗糙",
    "慢",
    "偏大",
    "偏小",
    "色差",
    "缩水",
    "掉色",
    "开线",
    "线头",
    "退货",
    "退款",
    "不推荐",
]

POSITIVE_WORDS = ["好看", "满意", "喜欢", "合适", "舒服", "精致", "不错", "推荐", "还会", "回购"]


def tokenize_comment(text: str) -> list[str]:
    text = safe_text(text)
    if not text:
        return []
    try:
        import jieba  # type: ignore

        tokens = [safe_text(token) for token in jieba.lcut(text)]
    except Exception:
        tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]+", text)
    stop_words = {"这个", "一个", "还是", "就是", "没有", "不是", "感觉", "真的", "比较", "非常", "有点"}
    return [token for token in tokens if len(token) >= 2 and token not in stop_words]


def price_band(price: float | None, bands: list[dict[str, Any]]) -> str:
    if price is None:
        return "未知"
    for band in bands:
        lower = band.get("min")
        upper = band.get("max")
        if lower is None:
            lower_ok = True
        elif band.get("min_exclusive"):
            lower_ok = price > float(lower)
        else:
            lower_ok = price >= float(lower)

        if upper is None:
            upper_ok = True
        elif band.get("max_inclusive"):
            upper_ok = price <= float(upper)
        else:
            upper_ok = price < float(upper)
        if lower_ok and upper_ok:
            return str(band["name"])
    return "未知"


def analyze_products(products: list[dict[str, Any]], bands: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched: list[dict[str, Any]] = []
    band_counts: Counter[str] = Counter()
    band_price_sum: defaultdict[str, float] = defaultdict(float)
    band_price_count: Counter[str] = Counter()
    band_sales_sum: defaultdict[str, int] = defaultdict(int)

    for product in products:
        price = product.get("price")
        if price is None:
            price = parse_price(product.get("price_text"))
        band = price_band(price, bands)
        product = dict(product)
        product["price"] = price
        product["price_band"] = band
        band_counts[band] += 1
        if price is not None:
            band_price_sum[band] += float(price)
            band_price_count[band] += 1
        if product.get("monthly_sales") is not None:
            band_sales_sum[band] += int(product["monthly_sales"])
        enriched.append(product)

    total = max(1, len(enriched))
    hot_band = ""
    if band_sales_sum:
        hot_band = max(band_sales_sum.items(), key=lambda item: (item[1], band_counts[item[0]]))[0]
    elif band_counts:
        hot_band = max(band_counts.items(), key=lambda item: item[1])[0]

    stats: list[dict[str, Any]] = []
    for band in [b["name"] for b in bands] + (["未知"] if band_counts.get("未知") else []):
        count = band_counts.get(band, 0)
        avg = band_price_sum[band] / band_price_count[band] if band_price_count[band] else None
        ratio = count / total
        stats.append(
            {
                "price_band": band,
                "count": count,
                "ratio": ratio,
                "avg_price": round(avg, 2) if avg is not None else None,
                "sales_sum": band_sales_sum.get(band, 0),
                "is_hot_price_band": "是" if band == hot_band else "",
            }
        )

    avg_by_band = {row["price_band"]: row["avg_price"] for row in stats}
    ratio_by_band = {row["price_band"]: row["ratio"] for row in stats}
    for product in enriched:
        band = product.get("price_band", "未知")
        product["band_ratio"] = ratio_by_band.get(band, 0)
        product["band_avg_price"] = avg_by_band.get(band)
        product["hot_price_band"] = hot_band
        product.setdefault("notes", "")
    return enriched, stats


def match_topics(text: str) -> list[str]:
    text = safe_text(text)
    if not text:
        return []
    matches = []
    for topic, words in TOPIC_KEYWORDS.items():
        if any(word in text for word in words):
            matches.append(topic)
    return matches


def sentiment_label(review: dict[str, Any]) -> str:
    level = safe_text(review.get("comment_level"))
    if "好" in level:
        return "positive"
    if "中" in level:
        return "neutral"
    if "差" in level:
        return "negative"
    rating = review.get("rating")
    try:
        rating_value = float(rating) if rating not in (None, "") else None
    except (TypeError, ValueError):
        rating_value = None
    if rating_value is not None:
        if rating_value >= 4:
            return "positive"
        if rating_value <= 2:
            return "negative"
        return "neutral"
    text = safe_text(review.get("comment_text"))
    if any(word in text for word in NEGATIVE_WORDS):
        return "negative"
    if any(word in text for word in POSITIVE_WORDS):
        return "positive"
    return "neutral" if text else ""


def issue_tags(text: str, sentiment: str) -> list[str]:
    topics = match_topics(text)
    if sentiment == "positive":
        return []
    text = safe_text(text)
    has_negative = any(word in text for word in NEGATIVE_WORDS)
    return topics if has_negative or sentiment == "negative" else []


def _keywords_for_barrier(texts: list[str]) -> list[str]:
    counts: Counter[str] = Counter()
    for text in texts:
        for word in NEGATIVE_WORDS:
            if word in text:
                counts[word] += 1
    return [word for word, _ in counts.most_common(8)]


def analyze_reviews(reviews: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    sentiment_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    token_counts: Counter[str] = Counter()
    barrier_texts: list[str] = []

    for review in reviews:
        review = dict(review)
        sentiment = sentiment_label(review)
        topics = match_topics(review.get("comment_text", ""))
        issues = issue_tags(review.get("comment_text", ""), sentiment)
        review["matched_topics"] = "、".join(topics)
        review["sentiment_label"] = sentiment
        review["issue_tags"] = "、".join(issues)
        enriched.append(review)
        if review.get("crawl_status") == "ok" and sentiment:
            sentiment_counts[sentiment] += 1
            topic_counts.update(topics)
            issue_counts.update(issues)
            token_counts.update(tokenize_comment(review.get("comment_text", "")))
            if sentiment in {"negative", "neutral"}:
                barrier_texts.append(safe_text(review.get("comment_text")))

    valid_count = sum(sentiment_counts.values())
    positive_ratio = sentiment_counts["positive"] / valid_count if valid_count else 0
    top_pain_points = [
        {"pain_point": topic, "count": count}
        for topic, count in issue_counts.most_common(10)
    ]
    topic_summary = [
        {"topic": topic, "count": count}
        for topic, count in topic_counts.most_common()
    ]
    high_frequency_terms = [
        {"term": term, "count": count}
        for term, count in token_counts.most_common(30)
    ]
    barriers = _keywords_for_barrier(barrier_texts)
    satisfaction_summary = (
        f"有效评论{valid_count}条，满意度{positive_ratio:.1%}，"
        f"好评{sentiment_counts['positive']}条，中评{sentiment_counts['neutral']}条，差评{sentiment_counts['negative']}条"
    )
    top10_text = "；".join(f"{row['pain_point']}({row['count']})" for row in top_pain_points)
    barrier_text = "、".join(barriers) if barriers else "未识别到明显复购阻碍"

    for review in enriched:
        review["top10_pain_point"] = top10_text
        review["satisfaction_summary"] = satisfaction_summary
        review["repurchase_barrier_reason"] = barrier_text

    summary = {
        "sentiment_counts": dict(sentiment_counts),
        "satisfaction_ratio": positive_ratio,
        "satisfaction_summary": satisfaction_summary,
        "top_pain_points": top_pain_points,
        "topic_summary": topic_summary,
        "high_frequency_terms": high_frequency_terms,
        "repurchase_barrier_reason": barrier_text,
    }
    return enriched, summary
