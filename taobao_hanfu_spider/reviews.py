from __future__ import annotations

import json
import re
from typing import Any

from .browser import BrowserSession, maybe_pause_for_verification
from .models import Review
from .utils import human_delay, now_iso, safe_text


COMMENT_LEVELS = [
    ("好评", "1"),
    ("中评", "0"),
    ("差评", "-1"),
]

REVIEW_EVALUATE_JS = r"""
() => {
  const normalize = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const textFrom = (node) => normalize(node ? (node.innerText || node.textContent || '') : '');
  const contentSelectors = [
    '[class*="content"]',
    '[class*="Content"]',
    '[class*="text"]',
    '[class*="Text"]',
    '[class*="desc"]',
    '[class*="Desc"]',
    '[class*="feedback"]',
    '[class*="Feedback"]'
  ];
  const containerNodes = Array.from(document.querySelectorAll(
    [
      '[class*="rate"]',
      '[class*="Rate"]',
      '[class*="comment"]',
      '[class*="Comment"]',
      '[class*="review"]',
      '[class*="Review"]',
      '[class*="evaluate"]',
      '[class*="Evaluate"]',
      '[data-spm*="rate"]',
      'li',
      'article'
    ].join(',')
  ));
  const directTextNodes = Array.from(document.querySelectorAll(contentSelectors.join(',')));
  const nodes = [...directTextNodes, ...containerNodes];
  const seen = new Set();
  const comments = [];
  for (const node of nodes) {
    const textCandidates = [];
    for (const selector of contentSelectors) {
      for (const child of Array.from(node.querySelectorAll ? node.querySelectorAll(selector) : [])) {
        textCandidates.push(textFrom(child));
      }
    }
    textCandidates.push(textFrom(node));
    for (const rawText of textCandidates) {
      const text = normalize(rawText);
      if (!text || text.length < 8 || text.length > 1200 || seen.has(text)) continue;
      seen.add(text);
      const timeMatch = text.match(/20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}|(?:\d{1,2}月\d{1,2}日)/);
      const nickNode = node.querySelector && node.querySelector('[class*="nick"], [class*="Nick"], [class*="user"], [class*="User"], [class*="name"], [class*="Name"]');
      const skuNode = node.querySelector && node.querySelector('[class*="sku"], [class*="Sku"], [class*="spec"], [class*="Spec"]');
      comments.push({
        text,
        user_nickname: normalize(nickNode ? nickNode.innerText : ''),
        comment_time: timeMatch ? timeMatch[0] : '',
        sku_info: normalize(skuNode ? skuNode.innerText : '')
      });
    }
  }
  return comments;
}
"""


def parse_jsonp(text: str) -> dict[str, Any]:
    text = text.strip()
    start = text.find("(")
    end = text.rfind(")")
    if start >= 0 and end > start:
        text = text[start + 1 : end]
    return json.loads(text)


def extract_seller_id(html: str) -> str:
    patterns = [
        r'"sellerId"\s*:\s*"?(\d+)"?',
        r'"seller_id"\s*:\s*"?(\d+)"?',
        r'"userId"\s*:\s*"?(\d+)"?',
        r"sellerId\s*[:=]\s*['\"]?(\d+)",
        r"user_id=(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    return ""


def normalize_api_comment(raw: dict[str, Any], product: dict[str, Any], level: str) -> Review:
    rating = raw.get("score") or raw.get("rateScore")
    try:
        rating_value = float(rating) if rating not in (None, "") else None
    except (TypeError, ValueError):
        rating_value = None
    return Review(
        item_id=safe_text(product.get("item_id")),
        title=safe_text(product.get("title")),
        comment_level=level,
        rating=rating_value,
        comment_time=safe_text(raw.get("rateDate") or raw.get("feedbackDate") or raw.get("date")),
        user_nickname=safe_text(raw.get("displayUserNick") or raw.get("userNick") or raw.get("nick")),
        comment_text=safe_text(raw.get("rateContent") or raw.get("content") or raw.get("feedback")),
        sku_info=safe_text(raw.get("auctionSku") or raw.get("skuInfo")),
        source="rate.tmall.com/list_detail_rate",
        crawl_status="ok",
        failure_reason="",
    )


def parse_review_candidate(raw: dict[str, Any]) -> dict[str, str] | None:
    raw_text = safe_text(raw.get("text"))
    raw_user = safe_text(raw.get("user_nickname"))
    raw_sku = safe_text(raw.get("sku_info"))
    meta_pool = " ".join(
        part
        for part in (
            raw_text,
            raw_user,
            raw_sku,
        )
        if part
    )
    if not meta_pool:
        return None

    comment_time = extract_comment_time(meta_pool)
    sku_info = extract_sku_info(" ".join(part for part in (raw_sku, raw_text, raw_user) if part))
    user_nickname = extract_user_nickname(raw_user, comment_time, sku_info) if raw_user else ""
    if not user_nickname:
        user_nickname = extract_user_nickname(meta_pool, comment_time, sku_info)
    comment_source = raw_text or meta_pool
    comment_text = extract_review_body(comment_source, sku_info=sku_info, user_nickname=user_nickname, comment_time=comment_time)
    if not comment_text or not looks_like_real_review(comment_text):
        return None
    return {
        "user_nickname": user_nickname,
        "comment_time": comment_time,
        "sku_info": sku_info,
        "comment_text": comment_text,
    }


def extract_comment_time(text: str) -> str:
    text = safe_text(text)
    patterns = (
        r"20\d{2}年\d{1,2}月\d{1,2}日",
        r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}",
        r"\d{1,2}月\d{1,2}日",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return ""


def extract_sku_info(text: str) -> str:
    text = safe_text(text)
    match = re.search(r"已购[:：]\s*", text)
    if not match:
        return ""
    start = match.start()
    after = text[match.end() :]
    comment_starts = (
        "面料",
        "尺码",
        "版型",
        "做工",
        "质量",
        "衣服",
        "物流",
        "客服",
        "穿着",
        "上身",
        "宝贝",
        "收到",
        "短袖",
        "裙子",
        "颜色",
        "大小",
        "质感",
        "手感",
        "物美",
        "东西",
        "不扎",
        "可以",
        "很",
        "挺",
        "0 0",
    )
    end = len(text)
    for marker in comment_starts:
        marker_index = after.find(marker)
        if marker_index > 0:
            end = min(end, match.end() + marker_index)
    sku = text[start:end]
    return safe_text(sku.rstrip("，。,.!！"))


def extract_user_nickname(text: str, comment_time: str = "", sku_info: str = "") -> str:
    text = safe_text(text)
    cut = text
    for marker in (comment_time, sku_info, "已购"):
        if marker and marker in cut:
            cut = cut.split(marker, 1)[0]
    cut = re.sub(r"\s+", " ", cut).strip(" ·:-：")
    if len(cut) > 32 or is_review_chrome_text(cut):
        return ""
    return cut


def looks_like_real_review(text: str) -> bool:
    text = safe_text(text)
    if len(text) < 8:
        return False
    if is_default_or_empty_review(text):
        return False
    if is_review_chrome_text(text):
        return False
    service_markers = (
        "平均",
        "小时发货",
        "秒回复",
        "发货 至",
        "预计",
        "保障",
        "店铺",
        "客服平均",
        "物流服务",
        "商品详情",
        "宝贝描述",
        "加入购物车",
        "立即购买",
        "查看全部评价" ,
    )
    if any(marker in text for marker in service_markers):
        return False
    review_markers = (
        "面料",
        "尺码",
        "色差",
        "做工",
        "版型",
        "质量",
        "客服",
        "物流",
        "发货",
        "穿",
        "上身",
        "好看",
        "满意",
        "差评",
        "中评",
        "好评",
    )
    has_date = re.search(r"20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}|\d{1,2}月\d{1,2}日", text)
    return bool(has_date or any(marker in text for marker in review_markers))


def is_default_or_empty_review(text: str) -> bool:
    text = safe_text(text)
    default_patterns = (
        r"^\d+位?买家默认好评$",
        r"^近半?年?\d+位?买家默认好评$",
        r"^此用户没有填写评价$",
        r"^系统默认好评$",
        r"^默认好评$",
        r"^该用户觉得商品不错$",
    )
    return any(re.search(pattern, text) for pattern in default_patterns)


def is_review_chrome_text(text: str) -> bool:
    text = safe_text(text)
    if not text:
        return True
    chrome_markers = (
        "用户评价",
        "好评率",
        "为你展示真实评价",
        "默认排序",
        "款式筛选",
        "全部 图/视频",
        "追评",
        "有图",
        "视频",
        "当前商品无评价",
    )
    if any(marker in text for marker in chrome_markers):
        return True
    if re.fullmatch(r"(全部|好评|中评|差评|追评|有图|视频|\d+\+?)", text):
        return True
    return False


class ReviewCrawler:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def crawl(self, products: list[dict[str, Any]]) -> list[Review]:
        output: list[Review] = []
        with BrowserSession(self.config) as session:
            page = session.new_page()
            for index, product in enumerate(products, start=1):
                print(f"[{index}/{len(products)}] 抓取评论: {product.get('title', '')[:50]}")
                comments = self._crawl_one_product(page, product)
                output.extend(comments)
                human_delay(
                    float(self.config.get("min_delay_seconds", 2)),
                    float(self.config.get("max_delay_seconds", 6)),
                )
        return output

    def _crawl_one_product(self, page, product: dict[str, Any]) -> list[Review]:
        target = int(self.config["reviews_per_product"])
        item_url = safe_text(product.get("item_url"))
        if not item_url:
            return [self._failed(product, "missing_item_url")]

        try:
            page.goto(item_url, wait_until="domcontentloaded")
            maybe_pause_for_verification(page, "商品详情页")
            html = page.content()
        except Exception as exc:
            return [self._failed(product, f"open_item_failed: {exc}")]

        seller_id = extract_seller_id(html)
        comments = self._crawl_visible_page_comments(page, product, target)
        if not comments and not bool(self.config.get("review_page_only", True)) and seller_id:
            comments = self._crawl_rate_api(page, product, seller_id, target)
        if not comments:
            return [self._failed(product, "no_reviews_from_evaluate_module")]
        return comments[:target]

    def _crawl_rate_api(self, page, product: dict[str, Any], seller_id: str, target: int) -> list[Review]:
        item_id = safe_text(product.get("item_id"))
        if not item_id:
            return []
        results: list[Review] = []
        seen: set[tuple[str, str, str]] = set()
        per_level_limit = max(1, target // len(COMMENT_LEVELS) + 1)
        for level_name, rate_type in COMMENT_LEVELS:
            page_no = 1
            while len([r for r in results if r.comment_level == level_name]) < per_level_limit and len(results) < target:
                params = {
                    "itemId": item_id,
                    "sellerId": seller_id,
                    "currentPage": str(page_no),
                    "rateType": rate_type,
                    "order": "1",
                    "append": "0",
                    "content": "1",
                    "callback": "jsonp_tb_rate",
                }
                try:
                    response = page.context.request.get(
                        "https://rate.tmall.com/list_detail_rate.htm",
                        params=params,
                        headers={"referer": safe_text(product.get("item_url"))},
                        timeout=int(self.config.get("timeout_ms", 30_000)),
                    )
                    text = response.text()
                    if "bxpunish" in text or "验证码" in text:
                        break
                    payload = parse_jsonp(text)
                    rate_list = payload.get("rateDetail", {}).get("rateList", [])
                except Exception:
                    break
                if not rate_list:
                    break
                for raw in rate_list:
                    review = normalize_api_comment(raw, product, level_name)
                    key = (review.user_nickname, review.comment_time, review.comment_text)
                    if review.comment_text and key not in seen:
                        seen.add(key)
                        results.append(review)
                page_no += 1
                human_delay(0.6, 1.6)
        return results[:target]

    def _crawl_visible_page_comments(self, page, product: dict[str, Any], target: int) -> list[Review]:
        review_page = self._open_review_surface(page)
        if review_page is None:
            return []
        for _ in range(8):
            try:
                review_page.mouse.wheel(0, 1000)
                review_page.wait_for_timeout(900)
            except Exception:
                break
        try:
            raw_comments = review_page.evaluate(REVIEW_EVALUATE_JS)
        except Exception:
            return []

        rows: list[Review] = []
        seen: set[str] = set()
        for raw in raw_comments:
            parsed = parse_review_candidate(raw)
            if not parsed:
                continue
            text = parsed["comment_text"]
            if text in seen:
                continue
            seen.add(text)
            rows.append(
                Review(
                    item_id=safe_text(product.get("item_id")),
                    title=safe_text(product.get("title")),
                    comment_level=_infer_comment_level(text),
                    rating=None,
                    comment_time=parsed["comment_time"],
                    user_nickname=parsed["user_nickname"],
                    comment_text=text,
                    sku_info=parsed["sku_info"],
                    source="evaluate_module",
                    crawl_status="ok",
                )
            )
            if len(rows) >= target:
                break
        return rows

    def _open_review_surface(self, page):
        clicked_reviews = self._click_text(page, ("评价", "累计评价", "宝贝评价", "评论"))
        if not clicked_reviews:
            print("未找到商品页评价入口。")
            return None
        page.wait_for_timeout(1500)
        target_page = self._click_text(
            page,
            ("查看全部评价", "查看全部评论", "全部评价", "全部评论", "查看更多评价"),
            allow_new_page=True,
        )
        if target_page is None:
            print("未找到“查看全部评价”入口，避免误抓商品详情文案。")
            return None
        target_page.wait_for_timeout(2000)
        maybe_pause_for_verification(target_page, "评价列表页")
        return target_page

    def _click_text(self, page, texts: tuple[str, ...], allow_new_page: bool = False):
        for text in texts:
            try:
                locator = page.get_by_text(text, exact=False).first
                if not locator.count():
                    continue
                before_pages = list(page.context.pages) if allow_new_page else []
                locator.click(timeout=3500)
                page.wait_for_timeout(1200)
                if allow_new_page:
                    after_pages = list(page.context.pages)
                    if len(after_pages) > len(before_pages):
                        new_page = after_pages[-1]
                        new_page.wait_for_load_state("domcontentloaded", timeout=8000)
                        return new_page
                    return page
                return page
            except Exception:
                continue
        return None

    def _failed(self, product: dict[str, Any], reason: str) -> Review:
        return Review(
            item_id=safe_text(product.get("item_id")),
            title=safe_text(product.get("title")),
            comment_level="",
            rating=None,
            comment_time=now_iso(),
            user_nickname="",
            comment_text="",
            sku_info="",
            source="",
            crawl_status="failed",
            failure_reason=reason,
        )


def _infer_comment_level(text: str) -> str:
    if "差评" in text:
        return "差评"
    if "中评" in text:
        return "中评"
    if "好评" in text:
        return "好评"
    return "未知"


def _clean_comment_text(text: str) -> str:
    text = safe_text(text)
    text = re.sub(r"^(好评|中评|差评)\s*", "", text)
    text = re.sub(r"20\d{2}[-./年]\d{1,2}[-./月]\d{1,2}[日]?", "", text).strip()
    return text


def extract_review_body(text: str, sku_info: str = "", user_nickname: str = "", comment_time: str = "") -> str:
    text = _clean_comment_text(text)
    if not text:
        return ""
    for part in (sku_info, user_nickname, comment_time):
        if part:
            text = safe_text(text.replace(part, " "))
    text = re.sub(r"已购[:：]\s*.+?(?=\s+(?:面料|尺码|版型|做工|质量|衣服|物流|客服|穿着|上身|宝贝|收到|短袖|裙子|颜色|大小|很|挺|不|0\s*0|[，。,.!！])|$)", " ", text)
    text = re.sub(r"^\s*0\s*0\s*", "", text)
    lines = [safe_text(line) for line in re.split(r"[\r\n]+| {2,}", text)]
    candidates = []
    for line in lines:
        line = _clean_comment_text(line)
        if not line or is_review_chrome_text(line) or is_default_or_empty_review(line):
            continue
        candidates.append(line)
    if candidates:
        return max(candidates, key=len)
    if is_review_chrome_text(text) or is_default_or_empty_review(text):
        return ""
    return text
