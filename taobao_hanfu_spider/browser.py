from __future__ import annotations

from pathlib import Path
from typing import Any


PLAYWRIGHT_HELP = """
Playwright is required for live Taobao crawling.

Use a virtual environment:
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  python -m playwright install chromium
"""


class BrowserSession:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.playwright = None
        self.context = None

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(PLAYWRIGHT_HELP.strip()) from exc

        profile_dir = Path(str(self.config["profile_dir"]))
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = sync_playwright().start()
        browser = self.playwright.chromium
        launch_kwargs = {
            "user_data_dir": str(profile_dir),
            "headless": bool(self.config.get("headless", False)),
            "slow_mo": int(self.config.get("slow_mo_ms", 0)),
            "viewport": {"width": 1440, "height": 1100},
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
            ],
        }
        try:
            self.context = browser.launch_persistent_context(channel="chrome", **launch_kwargs)
        except Exception:
            self.context = browser.launch_persistent_context(**launch_kwargs)
        self.context.set_default_timeout(int(self.config.get("timeout_ms", 30_000)))
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()

    def new_page(self):
        if not self.context:
            raise RuntimeError("BrowserSession is not active")
        if self.context.pages:
            return self.context.pages[0]
        return self.context.new_page()


def pause_for_manual_login(page) -> None:
    page.goto("https://www.taobao.com", wait_until="domcontentloaded")
    print("浏览器已打开淘宝首页。请在浏览器中手动扫码登录，完成后回到终端按 Enter。")
    input("登录完成后按 Enter 继续...")
    page.reload(wait_until="domcontentloaded")
    print("登录态已保存在持久化浏览器目录中。")


def maybe_pause_for_verification(page, reason: str = "") -> None:
    url = page.url.lower()
    body_text = ""
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception:
        body_text = ""
    markers = ("验证码", "滑块", "安全验证", "verify", "login.taobao.com", "punish")
    if any(marker in url or marker in body_text for marker in markers):
        message = f"检测到可能的人机验证或登录页：{reason}".strip("：")
        print(message)
        input("请在浏览器中完成验证/登录后按 Enter 继续...")

