"""初回のみローカルで実行: 楽天ログイン → auth.json 生成"""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright
from utils.stealth import new_stealth_context

AUTH_JSON = Path(__file__).parent / "auth.json"

RAKUTEN_ID       = os.environ.get("RAKUTEN_ID", "")
RAKUTEN_PASSWORD = os.environ.get("RAKUTEN_PASSWORD", "")


async def setup():
    if not RAKUTEN_ID or not RAKUTEN_PASSWORD:
        raise EnvironmentError("RAKUTEN_ID と RAKUTEN_PASSWORD を環境変数に設定してください")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await new_stealth_context(browser)
        page = await context.new_page()

        print("楽天にログイン中...")
        await page.goto(
            "https://grp01.id.rakuten.co.jp/rms/nid/login?service_id=top",
            wait_until="domcontentloaded",
        )
        await page.fill('input[name="u"]', RAKUTEN_ID)
        await page.fill('input[name="p"]', RAKUTEN_PASSWORD)
        await page.click('input[type="submit"], button[type="submit"]')
        await page.wait_for_load_state("networkidle", timeout=20000)

        await context.storage_state(path=str(AUTH_JSON))
        print(f"auth.json を保存しました: {AUTH_JSON}")
        print("GitHub Secrets の RAKUTEN_AUTH_JSON にこのファイルの内容を登録してください。")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(setup())
