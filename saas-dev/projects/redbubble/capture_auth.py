"""
capture_auth.py — システムのChromeでログインしてセッション保存
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

DATA_DIR  = Path(__file__).parent / "data"
AUTH_FILE = DATA_DIR / "rb_auth.json"


async def main():
    async with async_playwright() as p:
        # インストール済みのChromeを使う（Chromiumダウンロード不要）
        browser = await p.chromium.launch(
            channel="chrome",
            headless=False,
        )
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.redbubble.com/auth/login")

        print("Chromeが開きました。Redbubble にログインしてください。")
        print("ログイン完了後、Enterを押してください...")
        input()

        storage = await context.storage_state()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_text(
            json.dumps(storage, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"✓ セッション保存: {AUTH_FILE}")
        await browser.close()


asyncio.run(main())
