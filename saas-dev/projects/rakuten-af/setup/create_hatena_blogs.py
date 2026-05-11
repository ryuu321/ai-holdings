"""
はてなブログ追加作成スクリプト（同一アカウント）
実行: python setup/create_hatena_blogs.py

やること:
  1. 既存のはてなアカウントでログイン
  2. ブログを3つ追加作成
  3. 各ブログのBLOG_IDを取得
  4. hatena_blogs.json に保存
     → 次に register_github_secrets.py を実行

必要: pip install playwright && playwright install chromium
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

BLOGS_TO_CREATE = [
    {"name": "おすすめ商品ランキング館", "domain": "ryuu-ranking-01"},
    {"name": "毎日のお買い得情報",       "domain": "ryuu-deal-02"},
    {"name": "楽天セレクション",         "domain": "ryuu-select-03"},
]

BLOGS_FILE = Path(__file__).parent / "hatena_blogs.json"


def pause(msg: str):
    input(f"\n[手動操作] {msg}\nEnterキーで続行...")


async def main():
    blogs = []

    if BLOGS_FILE.exists():
        blogs = json.loads(BLOGS_FILE.read_text(encoding="utf-8"))
        print(f"既存: {len(blogs)}件。残り{len(BLOGS_TO_CREATE) - len(blogs)}件を作成します。")

    remaining = BLOGS_TO_CREATE[len(blogs):]
    if not remaining:
        print("全ブログの作成が完了しています。register_github_secrets.py を実行してください。")
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=400)
        context = await browser.new_context()
        page = await context.new_page()

        # ログイン
        await page.goto("https://www.hatena.ne.jp/login")
        pause("はてなにログインしてください（既存アカウント）。ログイン完了したらEnter。")

        for blog in remaining:
            print(f"\nブログ作成: {blog['name']} ({blog['domain']})")

            await page.goto("https://blog.hatena.ne.jp/-/create")
            await page.wait_for_load_state("networkidle")

            # タイトル入力
            for sel in ['input[name="blog[title]"]', 'input[name="title"]', 'input[placeholder*="タイトル"]']:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.fill(blog["name"])
                    break

            # サブドメイン入力
            for sel in ['input[name="blog[domain]"]', 'input[name="domain"]']:
                el = page.locator(sel).first
                if await el.count() > 0:
                    await el.fill(blog["domain"])
                    break

            pause(f"ブログ作成フォームを確認して「作成」ボタンを押してください。\n  作成後に表示されるブログURL（例: {blog['domain']}.hatenablog.com）を確認してEnter。")

            blog_id = input(f"  作成されたBLOG_IDを入力（例: {blog['domain']}.hatenablog.com）: ").strip()
            blogs.append({"name": blog["name"], "blog_id": blog_id, "index": len(blogs) + 1})
            BLOGS_FILE.write_text(json.dumps(blogs, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  保存: {blog_id}")

        await browser.close()

    print(f"\n完了。次のステップ: python setup/register_github_secrets.py")


if __name__ == "__main__":
    asyncio.run(main())
