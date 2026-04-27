from __future__ import annotations

import argparse
from dataclasses import asdict
from typing import Any

from .analysis import analyze_products, analyze_reviews
from .browser import BrowserSession, pause_for_manual_login
from .config import data_path, load_config, output_path
from .exporters import export_products, export_reviews
from .products import ProductCrawler
from .reviews import ReviewCrawler
from .utils import read_json, write_json


PRODUCTS_CACHE = "products_raw.json"
REVIEWS_CACHE = "reviews_raw.json"


def _load_products(config: dict[str, Any]) -> list[dict[str, Any]]:
    products = read_json(data_path(config, PRODUCTS_CACHE), default=[])
    if not products:
        raise SystemExit("未找到商品缓存，请先运行 crawl-products 或 run-all。")
    return products


def _load_reviews(config: dict[str, Any]) -> list[dict[str, Any]]:
    reviews = read_json(data_path(config, REVIEWS_CACHE), default=[])
    if not reviews:
        raise SystemExit("未找到评论缓存，请先运行 crawl-reviews 或 run-all。")
    return reviews


def cmd_login(config: dict[str, Any]) -> None:
    with BrowserSession(config) as session:
        page = session.new_page()
        pause_for_manual_login(page)


def cmd_crawl_products(config: dict[str, Any]) -> list[dict[str, Any]]:
    crawler = ProductCrawler(config)
    products = [asdict(product) for product in crawler.crawl()]
    write_json(data_path(config, PRODUCTS_CACHE), products)
    print(f"已保存商品缓存：{data_path(config, PRODUCTS_CACHE)}，共 {len(products)} 条。")
    return products


def cmd_crawl_reviews(config: dict[str, Any]) -> list[dict[str, Any]]:
    products = _load_products(config)
    crawler = ReviewCrawler(config)
    reviews = [asdict(review) for review in crawler.crawl(products)]
    write_json(data_path(config, REVIEWS_CACHE), reviews)
    print(f"已保存评论缓存：{data_path(config, REVIEWS_CACHE)}，共 {len(reviews)} 条。")
    return reviews


def cmd_export(config: dict[str, Any]) -> None:
    products = _load_products(config)
    reviews = _load_reviews(config)
    analyzed_products, product_stats = analyze_products(products, config["price_bands"])
    analyzed_reviews, review_summary = analyze_reviews(reviews)
    products_file = output_path(config, str(config["products_excel"]))
    reviews_file = output_path(config, str(config["reviews_excel"]))
    export_products(products_file, analyzed_products, product_stats)
    export_reviews(reviews_file, analyzed_reviews, review_summary)
    print(f"已导出商品表：{products_file}")
    print(f"已导出评论表：{reviews_file}")


def cmd_run_all(config: dict[str, Any]) -> None:
    cmd_crawl_products(config)
    cmd_crawl_reviews(config)
    cmd_export(config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="淘宝汉服商品与评论爬虫")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("login", help="打开真实浏览器，手动登录淘宝并保存登录态")
    subparsers.add_parser("crawl-products", help="采集淘宝汉服商品前100")
    subparsers.add_parser("crawl-reviews", help="基于商品缓存采集评论")
    subparsers.add_parser("export", help="基于缓存导出两个核心 Excel 文件")
    subparsers.add_parser("run-all", help="依次执行商品、评论、导出")
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.command == "login":
        cmd_login(config)
    elif args.command == "crawl-products":
        cmd_crawl_products(config)
    elif args.command == "crawl-reviews":
        cmd_crawl_reviews(config)
    elif args.command == "export":
        cmd_export(config)
    elif args.command == "run-all":
        cmd_run_all(config)
    else:
        parser.error(f"未知命令：{args.command}")

