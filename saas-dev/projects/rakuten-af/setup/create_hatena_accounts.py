"""
はてなアカウント3セット自動作成スクリプト
実行: python setup/create_hatena_accounts.py

やること:
  1. はてなアカウント登録（ブラウザを開いてフォーム入力）
  2. ブログ作成
  3. AtomPub APIキー取得
  4. hatena_credentials.json に保存
     → 次に register_github_secrets.py を実行してGitHubに登録

必要: pip install playwright && playwright install chromium
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

ACCOUNTS = [
    {
        "index": 1,
        "hatena_id":  "ryuu-af-01",
        "email":      "ryuumg03+hatena1@gmail.com",
        "password":   "AfBlog2024!1",
        "blog_name":  "おすすめ商品ランキング館",
        "blog_domain": "ryuu-af-01.hatenablog.com",
    },
    {
        "index": 2,
        "hatena_id":  "ryuu-af-02",
        "email":      "ryuumg03+hatena2@gmail.com",
        "password":   "AfBlog2024!2",
        "blog_name":  "毎日のお買い得情報",
        "blog_domain": "ryuu-af-02.hatenablog.com",
    },
    {
        "index": 3,
        "hatena_id":  "ryuu-af-03",
        "email":      "ryuumg03+hatena3@gmail.com",
        "password":   "AfBlog2024!3",
        "blog_name":  "楽天セレクション",
        "blog_domain": "ryuu-af-03.hatenablog.com",
    },
]

CRED_FILE = Path(__file__).parent / "hatena_credentials.json"


def pause(msg: str):
    input(f"\n[手動操作] {msg}\nEnterキーで続行...")


async def register_account(page, acct: dict):
    print(f"\n{'='*50}")
    print(f"[{acct['index']}/3] アカウント作成: {acct['hatena_id']}")

    await page.goto("https://www.hatena.ne.jp/register/input")
    await page.wait_for_load_state("networkidle")

    # はてなID
    if await page.locator('input[name="name"]').is_visible():
        await page.fill('input[name="name"]', acct["hatena_id"])

    # メールアドレス
    if await page.locator('input[name="mail"]').is_visible():
        await page.fill('input[name="mail"]', acct["email"])

    # パスワード
    if await page.locator('input[name="password"]').is_visible():
        await page.fill('input[name="password"]', acct["password"])

    print(f"  フォーム入力完了。送信してください...")
    pause(f"登録フォームを確認して「登録」ボタンを押してください。\n  メール確認が求められたら {acct['email']} を確認してリンクをクリックしてください。\n  完了したらEnterを押してください。")

    print(f"  アカウント登録完了を確認しました。")


async def create_blog(page, acct: dict):
    print(f"  ブログ作成中...")
    await page.goto("https://blog.hatena.ne.jp/-/create")
    await page.wait_for_load_state("networkidle")

    # ブログタイトル
    title_sel = 'input[name="blog[title]"], input[name="title"], input[placeholder*="タイトル"]'
    if await page.locator(title_sel).first.is_visible():
        await page.fill(title_sel, acct["blog_name"])

    # サブドメイン（hatena_id部分）
    domain_sel = 'input[name="blog[domain]"], input[name="domain"]'
    if await page.locator(domain_sel).first.is_visible():
        await page.fill(domain_sel, acct["hatena_id"])

    pause(f"ブログ作成フォームを確認して「作成」ボタンを押してください。\n  ブログURLは {acct['blog_domain']} になります。")
    print(f"  ブログ作成完了。")


async def get_api_key(page, acct: dict) -> str:
    print(f"  APIキー取得中...")

    # AtomPub設定ページ
    url = f"https://blog.hatena.ne.jp/{acct['hatena_id']}/{acct['blog_domain']}/config/detail"
    await page.goto(url)
    await page.wait_for_load_state("networkidle")

    # APIキーを探す
    api_key = ""
    selectors = [
        'input[name="api_key"]',
        'input[id="api_key"]',
        'input[readonly][value]',
    ]
    for sel in selectors:
        el = page.locator(sel).first
        if await el.is_visible():
            api_key = await el.get_attribute("value") or ""
            if api_key:
                break

    if not api_key:
        print(f"  APIキーが自動取得できませんでした。")
        pause(f"ブラウザの「AtomPub」セクションに表示されているAPIキーをコピーして次の入力欄に貼り付けてください。")
        api_key = input("  APIキーを入力: ").strip()

    print(f"  APIキー取得完了: {api_key[:8]}...")
    return api_key


async def main():
    credentials = []

    if CRED_FILE.exists():
        credentials = json.loads(CRED_FILE.read_text(encoding="utf-8"))
        done_ids = {c["hatena_id"] for c in credentials}
        remaining = [a for a in ACCOUNTS if a["hatena_id"] not in done_ids]
        print(f"既存の認証情報: {len(credentials)}件。残り{len(remaining)}件を処理します。")
    else:
        remaining = ACCOUNTS

    if not remaining:
        print("全アカウントの作成が完了しています。register_github_secrets.py を実行してください。")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=500)
        context = await browser.new_context()
        page = await context.new_page()

        for acct in remaining:
            await register_account(page, acct)
            await create_blog(page, acct)
            api_key = await get_api_key(page, acct)

            credentials.append({
                "index":     acct["index"],
                "hatena_id": acct["hatena_id"],
                "blog_id":   acct["blog_domain"],
                "api_key":   api_key,
                "password":  acct["password"],
                "email":     acct["email"],
            })
            CRED_FILE.write_text(json.dumps(credentials, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [{acct['index']}/3] 保存完了 → {CRED_FILE}")

        await browser.close()

    print(f"\n{'='*50}")
    print(f"全{len(credentials)}アカウントの情報を保存しました。")
    print(f"次のステップ: python setup/register_github_secrets.py")


if __name__ == "__main__":
    asyncio.run(main())
