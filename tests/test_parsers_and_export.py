import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from taobao_hanfu_spider.analysis import analyze_products, analyze_reviews
from taobao_hanfu_spider.config import DEFAULT_CONFIG
from taobao_hanfu_spider.exporters import export_products, export_reviews
from taobao_hanfu_spider.products import extract_products_from_legacy_html, parse_detail_price
from taobao_hanfu_spider.reviews import extract_review_body, looks_like_real_review, normalize_api_comment, parse_jsonp, parse_review_candidate
from taobao_hanfu_spider.utils import canonical_item_url


class ParserAndExportTest(unittest.TestCase):
    def test_legacy_product_parser(self):
        html = Path("tests/fixtures/search_legacy.html").read_text(encoding="utf-8")
        products = extract_products_from_legacy_html(html)
        self.assertEqual(len(products), 2)
        self.assertEqual(products[0]["item_id"], "100000001")
        self.assertEqual(products[1]["price"], 1299.0)
        self.assertEqual(products[1]["monthly_sales"], 10000)

    def test_review_jsonp_parser(self):
        text = Path("tests/fixtures/review_jsonp.txt").read_text(encoding="utf-8")
        payload = parse_jsonp(text)
        product = {"item_id": "100000001", "title": "汉服", "item_url": "https://item.taobao.com/item.htm?id=100000001"}
        review = normalize_api_comment(payload["rateDetail"]["rateList"][0], product, "好评")
        self.assertEqual(review.user_nickname, "买家A")
        self.assertIn("版型", review.comment_text)

    def test_review_filter_rejects_service_copy(self):
        self.assertFalse(looks_like_real_review("平均11小时发货"))
        self.assertFalse(looks_like_real_review("客服平均19秒回复"))
        self.assertFalse(looks_like_real_review("预计8小时内发货，明天18点前送达"))
        self.assertFalse(looks_like_real_review("用户评价 · 200+ 近3个月好评率高达100.0% 加冰de扎克喝王"))
        self.assertFalse(looks_like_real_review("近3个月好评率高达100.0%"))
        self.assertFalse(looks_like_real_review("用户评价 · 200+ 近3个月好评率高达100.0% 全部 图/视频2 追评0 为你展示真实评价 默认排序 款式筛选"))
        self.assertFalse(looks_like_real_review("近半年281位买家默认好评"))
        self.assertTrue(looks_like_real_review("面料舒服，版型很好看，上身很满意"))

    def test_extract_review_body_drops_default_empty_reviews(self):
        self.assertEqual(extract_review_body("近半年281位买家默认好评"), "")
        self.assertEqual(extract_review_body("用户评价 · 200+ 近3个月好评率高达100.0%"), "")
        self.assertEqual(extract_review_body("默认排序 款式筛选 全部 图/视频2 追评0"), "")
        self.assertEqual(extract_review_body("2026-04-01 面料舒服，版型很好看，上身很满意"), "面料舒服，版型很好看，上身很满意")

    def test_parse_review_candidate_splits_meta_fields(self):
        parsed = parse_review_candidate(
            {
                "text": "辣天使很积极 2026年4月10日 已购：M【推荐100-120斤】 / M黑色小标+白色小标【纯棉两件装】 面料品质：舒服 上身效果：好",
                "user_nickname": "",
                "sku_info": "",
            }
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["user_nickname"], "辣天使很积极")
        self.assertEqual(parsed["comment_time"], "2026年4月10日")
        self.assertIn("已购：M", parsed["sku_info"])
        self.assertEqual(parsed["comment_text"], "面料品质：舒服 上身效果：好")

        parsed = parse_review_candidate(
            {
                "text": "辣**极 2026年4月10日已购：M黑色小标+白色小标【纯棉两件装】 / M【推荐100-120斤】 质感舒服，面料手感也好，可以购买哟！",
            }
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["user_nickname"], "辣**极")
        self.assertIn("已购：M黑色小标", parsed["sku_info"])
        self.assertNotIn("质感舒服", parsed["sku_info"])
        self.assertEqual(parsed["comment_text"], "质感舒服，面料手感也好，可以购买哟！")

        parsed = parse_review_candidate(
            {
                "text": "物流很快，手感还不错，物美价廉，有需要会再回购",
                "user_nickname": "辣**极 2026年4月10日已购：M黑色小标+白色小标【纯棉两件装】 / M【推荐100-120斤】",
                "sku_info": "",
            }
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["user_nickname"], "辣**极")
        self.assertEqual(parsed["comment_text"], "物流很快，手感还不错，物美价廉，有需要会再回购")

    def test_parse_review_candidate_drops_no_body(self):
        self.assertIsNone(parse_review_candidate({"text": "近半年281位买家默认好评"}))
        self.assertIsNone(parse_review_candidate({"text": "已购：M【推荐100-120斤】 / M黑色小标"}))
        self.assertIsNone(parse_review_candidate({"text": "用户评价 · 200+ 近3个月好评率高达100.0%"}))

    def test_detail_price_priority(self):
        self.assertEqual(parse_detail_price("券后 ￥ 68 优惠前 ￥ 78"), 68.0)
        self.assertEqual(parse_detail_price("优惠前 ￥ 78"), 78.0)

    def test_canonical_item_url(self):
        self.assertEqual(
            canonical_item_url("https://item.taobao.com/item.htm?id=1029450996118&skuId=1&spm=abc&utparam=x"),
            "https://item.taobao.com/item.htm?id=1029450996118",
        )
        self.assertEqual(
            canonical_item_url("//detail.tmall.com/item.htm?id=828614673880&skuId=2"),
            "https://detail.tmall.com/item.htm?id=828614673880",
        )

    def test_export_xlsx_files(self):
        products = [
            {"rank": 1, "item_id": "1", "title": "汉服A", "price": 199.0, "monthly_sales": 100, "shop_name": "店A", "item_url": "https://item.taobao.com/item.htm?id=1", "crawl_time": "now", "notes": ""},
            {"rank": 2, "item_id": "2", "title": "汉服B", "price": 650.0, "monthly_sales": 300, "shop_name": "店B", "item_url": "https://item.taobao.com/item.htm?id=2", "crawl_time": "now", "notes": ""},
        ]
        reviews = [
            {"item_id": "1", "title": "汉服A", "comment_level": "好评", "rating": 5, "comment_time": "2026-04-01", "user_nickname": "A", "comment_text": "面料舒服，版型好", "sku_info": "", "source": "fixture", "crawl_status": "ok", "failure_reason": ""},
            {"item_id": "2", "title": "汉服B", "comment_level": "差评", "rating": 2, "comment_time": "2026-04-02", "user_nickname": "B", "comment_text": "色差明显，发货慢", "sku_info": "", "source": "fixture", "crawl_status": "ok", "failure_reason": ""},
        ]
        analyzed_products, stats = analyze_products(products, DEFAULT_CONFIG["price_bands"])
        analyzed_reviews, summary = analyze_reviews(reviews)
        with tempfile.TemporaryDirectory() as tmp:
            products_path = Path(tmp) / "hanfu_products.xlsx"
            reviews_path = Path(tmp) / "hanfu_reviews.xlsx"
            export_products(products_path, analyzed_products, stats)
            export_reviews(reviews_path, analyzed_reviews, summary)
            self.assertTrue(products_path.exists())
            self.assertTrue(reviews_path.exists())
            with ZipFile(products_path) as zf:
                self.assertIn("xl/workbook.xml", zf.namelist())
            with ZipFile(reviews_path) as zf:
                self.assertIn("xl/worksheets/sheet2.xml", zf.namelist())


if __name__ == "__main__":
    unittest.main()
