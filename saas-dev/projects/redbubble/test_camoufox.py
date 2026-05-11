"""camoufoxでアップロードページにアクセスできるか確認"""
import asyncio
import json
from pathlib import Path
from camoufox.async_api import AsyncCamoufox

AUTH_FILE = Path(__file__).parent / "data" / "rb_auth.json"
UPLOAD_URL = "https://www.redbubble.com/portfolio/images/new"


async def test():
    # 保存済みクッキーを読み込む
    storage = json.loads(AUTH_FILE.read_text(encoding="utf-8")) if AUTH_FILE.exists() else None
    cookies = storage.get("cookies", []) if storage else []

    async with AsyncCamoufox(headless=False, humanize=True) as browser:
        page = await browser.new_page()

        # クッキーを注入
        if cookies:
            await page.context.add_cookies(cookies)
            print(f"  クッキー注入: {len(cookies)}件")

        print("  アップロードページへ...")
        await page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=30000)

        CF_TITLES = {"just a moment", "しばらくお待ち", "please wait", "checking your browser"}

        # 最大60秒待機
        for i in range(30):
            title = await page.title()
            content = await page.content()
            has_input = 'type="file"' in content
            print(f"  [{i*2}s] タイトル: {title} / file input: {has_input}")
            if has_input:
                print("  ✓ アップロードページ到達！")
                await page.screenshot(path="test_camoufox_success.png")
                break
            if any(cf in title.lower() for cf in CF_TITLES) or "cloudflare" in content[:500].lower():
                await asyncio.sleep(2)
                continue
            # Cloudflare以外のページ（ログインリダイレクト等）
            print(f"  → 別ページに遷移: {page.url}")
            await page.screenshot(path="test_camoufox_other.png")
            break
        else:
            print("  ✗ 60秒タイムアウト")
            await page.screenshot(path="test_camoufox_timeout.png")

asyncio.run(test())
