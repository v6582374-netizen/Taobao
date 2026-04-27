# 淘宝汉服商品与评论爬虫

这是一个面向研究分析的淘宝汉服爬虫项目，使用真实浏览器和手动登录，不保存账号密码，不破解验证码。最终输出两个核心 Excel 文件：

- `output/hanfu_products.xlsx`
- `output/hanfu_reviews.xlsx`

## 环境准备

请使用虚拟环境，避免全局安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

核心清洗、分析、Excel 导出和测试只依赖标准库；真实抓取淘宝页面时才需要 Playwright。

## 使用流程

```bash
source .venv/bin/activate
python -m taobao_hanfu_spider login
python -m taobao_hanfu_spider crawl-products
python -m taobao_hanfu_spider crawl-reviews
python -m taobao_hanfu_spider export
```

也可以在登录后运行：

```bash
python -m taobao_hanfu_spider run-all
```

## 输出内容

当前默认恢复为最初目标：按销量采集“汉服”前 100 件商品。商品表的 `notes` 会写入 `source_page=...`，用于确认每条商品来自哪个搜索结果页。

由于淘宝对直跳 `s.taobao.com/search` 可能直接返回 `deny_h5` 风控页，商品采集默认启用人工导航模式：

1. `crawl-products` 会先打开淘宝首页，并尝试自动在首页搜索框输入“汉服”。
2. 你在浏览器里确认搜索结果为“汉服”，切到销量排序，停在第 1 页后回到终端按 Enter。
3. 程序采集当前页最多 50 个新商品。
4. 你按终端提示在浏览器里手动翻到下一页，回到终端按 Enter。
5. 程序会继续采集，直到达到 100 件；`max_product_pages` 只是异常情况下的安全上限。

商品表包含标题、标价、月销量、店铺名称、商品链接，并附带价格分层、各价格带占比、均价、爆款价位。

评论表按每件商品不少于 100 条的目标采集；如果页面实际可见评论不足或入口受限，会记录失败原因或实际采集数量。字段包含好评/中评/差评、评分、评论时间、用户昵称、评论内容，并围绕版型、色差、做工、发货、尺码、面料、售后统计高频问题、痛点 Top10、整体满意度、复购阻碍原因。

评论采集只走商品页的“评价/累计评价”模块，并继续点击“查看全部评价/全部评论”等入口。找不到该入口时会写入失败原因，不再扫描商品详情整页，避免把“平均发货”“客服回复”“预计送达”等无关信息误当成用户评价。

## 注意事项

- 淘宝搜索和评论接口存在风控，运行过程中如果出现登录页、验证码或 `deny_h5`，请在打开的浏览器中手动处理到正常商品列表页后回到终端继续。
- 当前采集范围由 `config.yaml` 控制：`manual_product_navigation: true`、`auto_search_keyword: true`、`limit_products: 100`、`start_page: 1`、`end_page: null`、`max_product_pages: 10`、`products_per_page: 50`、`reviews_per_product: 100`。
- 评论不可采时会在评论表中写入失败原因，不用后续商品替补。
- 项目默认低频抓取，配置在 `config.yaml` 中调整。
- 开源项目仅作为调研参考，本实现没有直接复制无明确授权的代码。
