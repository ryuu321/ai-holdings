"""
uploader.py — Redbubble自動アップロード (Playwright)
ローカル: 専用Chromeプロファイルで永続化（Cloudflare対応）
CI: セッションクッキーで実行（Cloudflare通過できれば）
"""
import asyncio
import os
import json
from pathlib import Path
from playwright.async_api import async_playwright

DATA_DIR    = Path(__file__).parent / "data"
AUTH_FILE   = DATA_DIR / "rb_auth.json"
STATE_FILE  = DATA_DIR / "state.json"
DEBUG_DIR   = Path(__file__).parent / "logs"
# 専用Chromeプロファイル（Cloudflareの認識履歴を保持）
PROFILE_DIR = DATA_DIR / "chrome_profile"

RB_BASE    = "https://www.redbubble.com"
UPLOAD_URL = f"{RB_BASE}/portfolio/images/new"
LOGIN_URL  = f"{RB_BASE}/auth/login"

IS_CI = bool(os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"))


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"next_quote_index": 0, "uploaded": []}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def _screenshot(page, name: str):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(DEBUG_DIR / f"{name}.png"), full_page=False)
    except Exception:
        pass


async def _wait_for_upload_page(page) -> bool:
    """Cloudflareチャレンジが解決されてアップロードページが表示されるまで待つ"""
    for i in range(20):  # 最大40秒
        try:
            content = await page.content()
            title   = await page.title()
            if 'type="file"' in content:
                return True
            if "しばらく" in title or "challenge" in title.lower() or "cloudflare" in content.lower()[:200]:
                if i == 0:
                    print("  [Cloudflare] チャレンジ解決待機中...")
                await asyncio.sleep(2)
                continue
            # その他のページ（ログイン等）
            print(f"  [WARN] 予期しないページ: {title} / {page.url}")
            return False
        except Exception:
            await asyncio.sleep(1)
    return False


async def upload_design(image_path: Path, quote: dict, email: str, password: str) -> bool:
    """Redbubbleに1件アップロード"""
    title = _make_title(quote)
    tags  = quote.get("tags", [])[:10]

    async with async_playwright() as p:
        if IS_CI:
            # CI: 通常コンテキスト＋保存済みクッキー
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            storage = json.loads(AUTH_FILE.read_text(encoding="utf-8")) if AUTH_FILE.exists() else None
            context = await browser.new_context(
                storage_state=storage,
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()
        else:
            # ローカル: 専用プロファイルで永続化（Cloudflare履歴を保持）
            PROFILE_DIR.mkdir(parents=True, exist_ok=True)
            context = await p.chromium.launch_persistent_context(
                str(PROFILE_DIR),
                channel="chrome",
                headless=False,
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else await context.new_page()

        # セッション確認
        await page.goto(f"{RB_BASE}/portfolio/manage_works",
                        wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(3)
        await _screenshot(page, "03_session_check")
        print(f"  [セッション確認] URL: {page.url}")

        if "login" in page.url or "auth" in page.url:
            print("  → ログイン必要 → ブラウザでログインしてください（30秒以内）")
            if IS_CI:
                await context.close() if IS_CI else await context.browser.close()
                return False
            # ローカル: ログインページに遷移してユーザーが手動ログイン
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(30)  # 手動ログイン待機
            if "login" in page.url or "auth" in page.url:
                print("  ログイン未完了")
                await context.close()
                return False

        # アップロードページへ
        print(f"  アップロード開始: {title}")
        await page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=20000)
        await _screenshot(page, "04_upload_page")

        ok = await _wait_for_upload_page(page)
        if not ok:
            print(f"  アップロードページ取得失敗（Cloudflare? タイトル: {await page.title()}）")
            await _screenshot(page, "04_cf_blocked")
            if IS_CI:
                await context.close()
            else:
                await context.browser.close()
            return False

        print("  ファイル入力 検出 → アップロード中...")
        await _screenshot(page, "05_upload_ready")

        # ファイル選択
        try:
            await page.wait_for_selector('input[type="file"]', state="attached", timeout=10000)
            await page.set_input_files('input[type="file"]', str(image_path))
            print("  ファイル選択完了 → 処理待機...")
            await asyncio.sleep(10)
            await _screenshot(page, "06_after_file")
        except Exception as e:
            print(f"  ファイル選択失敗: {e}")
            if IS_CI:
                await context.close()
            else:
                await context.browser.close()
            return False

        # タイトル入力
        try:
            await page.fill('input[placeholder*="title" i], input[name*="title" i]', title, timeout=8000)
        except Exception:
            print("  タイトル欄スキップ")

        # タグ入力
        try:
            tag_input = page.locator('input[placeholder*="tag" i], input[name*="tag" i]').first
            for tag in tags:
                await tag_input.fill(tag)
                await page.keyboard.press("Enter")
                await asyncio.sleep(0.3)
        except Exception:
            print("  タグ欄スキップ")

        await asyncio.sleep(1)
        await _screenshot(page, "07_before_save")

        # 保存
        try:
            await page.click('button[type="submit"], button:has-text("Save"), button:has-text("Publish")',
                             timeout=8000)
            await asyncio.sleep(5)
            print(f"  → 投稿完了: {title}")
            await _screenshot(page, "08_done")
            if IS_CI:
                await context.close()
            else:
                await context.browser.close()
            return True
        except Exception as e:
            print(f"  保存ボタン失敗: {e}")
            await _screenshot(page, "07_save_failed")
            if IS_CI:
                await context.close()
            else:
                await context.browser.close()
            return False


def _make_title(quote: dict) -> str:
    first_line = quote["text"].split("\n")[0].strip()
    return f"{first_line} — MidnightTorii"[:60]


def _make_description(quote: dict) -> str:
    text = quote["text"].replace("\n", " ").strip()
    return (
        f"{text}\n\n"
        "MidnightTorii — Dark, mystical Japanese art. "
        "Moonlit torii gates, kitsune foxes, and glowing lanterns.\n\n"
        "Perfect for notebooks, laptops, water bottles, phone cases."
    )
