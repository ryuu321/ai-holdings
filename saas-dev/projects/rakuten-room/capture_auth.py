"""
楽天ROOMの認証情報をローカルでキャプチャするスクリプト。
実行後に auth.json が生成されるので、base64エンコードしてGitHub Secretsに登録する。

使い方:
  python capture_auth.py
  → ブラウザが開くので、楽天にログインしてROOMにも移動
  → 90秒後に自動でauth.jsonが保存される
  → auth_base64.txt の内容を GitHub Secrets (RAKUTEN_AUTH_JSON) に登録
"""
import asyncio
import base64
from pathlib import Path
from playwright.async_api import async_playwright

AUTH_JSON = Path(__file__).parent / "auth.json"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print("ブラウザを開いています...")
        await page.goto(
            "https://grp01.id.rakuten.co.jp/rms/nid/login?service_id=room&return_url=https://room.rakuten.co.jp/",
            timeout=60000, wait_until="domcontentloaded"
        )

        print("\n==============================================")
        print("1. ブラウザで楽天にログインしてください")
        print("2. room.rakuten.co.jp に自動遷移するのを確認")
        print("3. 右上にアカウント名が表示されたらOK")
        print("==============================================")
        print("\n300秒後に自動でcookieをキャプチャします...")
        for i in range(300, 0, -10):
            print(f"  残り {i}秒...")
            await asyncio.sleep(10)

        # ROOMにいない場合は遷移を試みる
        try:
            if "room.rakuten.co.jp" not in page.url:
                print(f"現在のURL: {page.url} → ROOMへ移動...")
                await page.goto("https://room.rakuten.co.jp/", timeout=60000, wait_until="domcontentloaded")
                await asyncio.sleep(5)
        except Exception as e:
            print(f"ROOM遷移エラー（無視）: {e}")

        # ログイン状態確認
        try:
            content = await page.content()
            status = "on" if '"login_status":"on"' in content else "off"
            print(f"ROOMログイン状態: {status}")
            if status == "off":
                print("警告: ROOMにログインできていません。auth.jsonは保存しますが効果が薄い可能性があります。")
        except Exception:
            print("ログイン状態確認スキップ")

        # cookieを保存（エラーがあっても保存を試みる）
        try:
            await context.storage_state(path=str(AUTH_JSON))
            print(f"\nauth.json を保存しました: {AUTH_JSON}")
        except Exception as e:
            print(f"保存エラー: {e}")
            await browser.close()
            return

        # base64エンコード
        encoded = base64.b64encode(AUTH_JSON.read_bytes()).decode()
        out = Path(__file__).parent / "auth_base64.txt"
        out.write_text(encoded, encoding="utf-8")

        print("\n==============================================")
        print("auth_base64.txt に保存しました")
        print("この内容を GitHub Secrets に登録してください:")
        print("  Secret名: RAKUTEN_AUTH_JSON")
        print("  場所: https://github.com/ryuu321/ai-holdings/settings/secrets/actions")
        print("==============================================")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
