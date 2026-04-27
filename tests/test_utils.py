import unittest

from taobao_hanfu_spider.analysis import match_topics, price_band
from taobao_hanfu_spider.config import DEFAULT_CONFIG, load_config
from taobao_hanfu_spider.utils import parse_price, parse_sales, taobao_search_url


class UtilsTest(unittest.TestCase):
    def test_parse_price(self):
        self.assertEqual(parse_price("¥199"), 199.0)
        self.assertEqual(parse_price("199.00"), 199.0)
        self.assertEqual(parse_price("1,299"), 1299.0)
        self.assertEqual(parse_price("200-600"), 200.0)

    def test_parse_sales(self):
        self.assertEqual(parse_sales("100+人付款"), 100)
        self.assertEqual(parse_sales("1万+人付款"), 10000)
        self.assertEqual(parse_sales("月销3000+"), 3000)

    def test_search_url_includes_page_and_offset(self):
        self.assertIn("page=1", taobao_search_url("汉服", 1))
        self.assertIn("s=0", taobao_search_url("汉服", 1))
        self.assertIn("page=2", taobao_search_url("汉服", 2))
        self.assertIn("s=44", taobao_search_url("汉服", 2))

    def test_default_config_pages_until_limit(self):
        config = load_config("config.yaml")
        self.assertEqual(config["limit_products"], 100)
        self.assertIsNone(config["end_page"])
        self.assertGreaterEqual(config["max_product_pages"], 4)

    def test_price_band_boundaries(self):
        bands = DEFAULT_CONFIG["price_bands"]
        self.assertEqual(price_band(199.99, bands), "平价(<200)")
        self.assertEqual(price_band(200, bands), "中端(200-600)")
        self.assertEqual(price_band(600, bands), "中高端(600-1500)")
        self.assertEqual(price_band(1500, bands), "中高端(600-1500)")
        self.assertEqual(price_band(1500.01, bands), "高端(>1500)")

    def test_topic_matching(self):
        self.assertEqual(match_topics(""), [])
        topics = match_topics("版型不错，但是色差明显，做工也有线头")
        self.assertIn("版型", topics)
        self.assertIn("色差", topics)
        self.assertIn("做工", topics)


if __name__ == "__main__":
    unittest.main()
