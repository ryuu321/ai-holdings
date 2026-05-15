"""
楽天ROOMの認証情報をローカルでキャプチャするスクリプト。

使い方:
  python capture_auth.py
  → ブラウザが開くので楽天にログイン
  → ROOMページでMYROOMをクリック（SSO発火）
  → 自動検出してauth.jsonを保存
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

AUTH_JSON = Path(__file__).parent / "auth.json"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # Step1: 楽天ログイン
        print("ブラウザを開いています...")
        await page.goto(
            "https://grp01.id.rakuten.co.jp/rms/nid/login?service_id=top",
            timeout=60000, wait_until="domcontentloaded"
        )
        print("\n[Step 1] 楽天にログインしてください")
        input("ログイン完了後、Enterを押してください > ")

        # Step2: ROOMへ手動移動
        print("\n[Step 2] ブラウザのアドレスバーに以下を入力してEnterしてください:")
        print("  https://room.rakuten.co.jp/items")
        print("\n[Step 3] ROOMが表示されたら「MYROOM」または「マイルーム」をクリックしてください")
        print("  SSO認証が走り、ログイン済みのMYROOMページに遷移します")
        print("  遷移を検出したら自動でキャプチャします（最大60秒待機）...")

        # MYROOMクリック後のURL変化を検出（room_XXXXまたはmyページへの遷移）
        detected = False
        for _ in range(60):
            await asyncio.sleep(1)
            url = page.url
            if any(x in url for x in ["/room_", "/mypage", "/my/", "myroom"]):
                print(f"✓ MYROOMページ検出: {url}")
                detected = True
                break

        if not detected:
            print("自動検出できませんでした。現在のページでキャプチャします")
            print(f"現在URL: {page.url}")

        # セッション確立を待つ
        print("セッション確立中（5秒待機）...")
        await asyncio.sleep(5)

        # storage_state（クッキー＋localStorage）を保存
        await context.storage_state(path=str(AUTH_JSON))
        import json
        data = json.loads(AUTH_JSON.read_text())
        n_cookies = len(data.get("cookies", []))
        n_origins = len(data.get("origins", []))
        print(f"\n✓ auth.json 保存完了: Cookie {n_cookies}件 / Origin {n_origins}件")

        print("\n次のコマンドを実行してください:")
        print("  python slim_auth.py")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
