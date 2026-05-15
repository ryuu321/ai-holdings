"""auth.jsonの中身を確認し、ブラウザでROOM接続状態を視覚的に確認する"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

AUTH_JSON = Path(__file__).parent / "auth.json"

async def main():
    auth = json.loads(AUTH_JSON.read_text())
    all_cookies = auth.get("cookies", [])
    print(f"全クッキー数: {len(all_cookies)}")

    cookies = [
        {"name": c["name"], "value": c["value"],
         "domain": c.get("domain", "room.rakuten.co.jp"),
         "path": c.get("path", "/")}
        for c in all_cookies
        if "rakuten" in c.get("domain", "")
    ]
    print(f"rakutenドメインのクッキー数: {len(cookies)}")
    print("ドメイン一覧:")
    for c in all_cookies:
        print(f"  {c.get('domain', '?')} : {c['name']}")

    print("\nブラウザでROOMに接続します（ウィンドウが開きます）...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        await context.add_cookies(cookies)
        page = await context.new_page()

        await page.goto("https://room.rakuten.co.jp/items",
                        wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        content = await page.content()
        url = page.url
        title = await page.title()

        print(f"\nURL: {url}")
        print(f"タイトル: {title}")

        # 複数のログイン指標を確認
        checks = {
            '"login_status":"on"': '"login_status":"on"' in content,
            '"loginStatus":"on"': '"loginStatus":"on"' in content,
            '"isLoggedIn":true': '"isLoggedIn":true' in content,
            '"is_login":true': '"is_login":true' in content,
            '"login_status": "on"': '"login_status": "on"' in content,
        }
        print("\nログイン指標チェック:")
        for k, v in checks.items():
            print(f"  {k}: {v}")

        # ページ内の login 関連文字列を探す
        import re
        login_matches = re.findall(r'(?:login|Login|session)[^"]{0,30}', content)
        print(f"\nlogin関連文字列（最初の10件）: {login_matches[:10]}")

        print("\n=== ブラウザウィンドウを確認してください ===")
        print("ROOMにログイン状態で表示されていますか？")
        print("確認後、Enterを押してください...")
        input()
        await browser.close()

asyncio.run(main())
