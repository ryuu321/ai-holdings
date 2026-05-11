"""Gumroad ファイルアップロード & 公開 — Playwright (email/password)"""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

_ROOT = Path(__file__).parent.parent.parent.parent
load_dotenv(_ROOT / ".env")

GUMROAD_EMAIL    = os.environ.get("GUMLOAD_EMAIL", "")
GUMROAD_PASSWORD = os.environ.get("GUMLOAD_PASSWORD", "")
SESSION_FILE     = Path(__file__).parent / "data" / "gumroad_session.json"

log = logging.getLogger(__name__)


def _login(page):
    """Gumroadにメール/パスワードで直接ログイン。2FA画面に遷移した場合はFalseを返す。"""
    page.goto("https://app.gumroad.com/login", wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    page.fill("input[name='email'], input[type='email']", GUMROAD_EMAIL)
    page.fill("input[name='password'], input[type='password']", GUMROAD_PASSWORD)
    page.click("button[type='submit'], input[type='submit']")
    try:
        page.wait_for_url("**/app.gumroad.com/**", timeout=15000)
    except Exception:
        pass
    if "two-factor" in page.url or "verification" in page.url:
        log.warning("2FA画面に遷移。headedモードで --setup を再実行してください")
        return False
    log.info("自動ログイン成功")
    return True


def _ensure_logged_in(page, context):
    """ログイン済みか確認し、必要なら自動再ログイン。成功したらTrue。"""
    if "login" not in page.url and "sign_in" not in page.url:
        return True
    if not GUMROAD_EMAIL or not GUMROAD_PASSWORD:
        log.error("セッション切れ・認証情報未設定（GUMLOAD_EMAIL/GUMLOAD_PASSWORD）")
        return False
    log.info("セッション切れ → メール/パスワードで自動再ログイン中...")
    ok = _login(page)
    if ok:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_FILE))
    return ok


def _new_context(p):
    """セッションファイルがあれば使い、なければ空のコンテキストを返す。"""
    if SESSION_FILE.exists():
        return p.chromium.launch(headless=True).new_context(storage_state=str(SESSION_FILE))
    return p.chromium.launch(headless=True).new_context()


def publish_product(permalink: str, file_path: str = None) -> bool:
    """
    Contentタブにファイルをアップロードして公開。
    セッション切れはメール/パスワードで自動回復。
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_args = {"storage_state": str(SESSION_FILE)} if SESSION_FILE.exists() else {}
        context = browser.new_context(**ctx_args)
        page = context.new_page()
        try:
            url = f"https://app.gumroad.com/products/{permalink}/edit/content"
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            if not _ensure_logged_in(page, context):
                return False

            # セッション回復後、ターゲットページに戻る
            if "login" not in page.url and "edit/content" not in page.url:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

            # ファイルアップロード
            if file_path and Path(file_path).exists():
                file_input = page.locator("input[type='file']").first
                file_input.set_input_files(str(file_path))
                log.info(f"ファイルセット: {Path(file_path).name}")
                page.wait_for_timeout(8000)

            # 「Publish and continue」クリック
            publish_btn = page.locator("button:has-text('Publish and continue')")
            publish_btn.wait_for(timeout=10000)
            publish_btn.click()
            page.wait_for_timeout(4000)
            log.info(f"公開完了: {permalink}")

            context.storage_state(path=str(SESSION_FILE))
            return True
        except Exception as e:
            log.error(f"公開エラー: {e}")
            try:
                page.screenshot(path=str(SESSION_FILE.parent / "error_screenshot.png"))
            except Exception:
                pass
            return False
        finally:
            browser.close()


def upload_cover_image(permalink: str, image_path: str) -> bool:
    """製品のカバー画像をアップロード。失敗時はFalseを返す（致命的でない）。"""
    if not Path(image_path).exists():
        log.warning(f"カバー画像が存在しない: {image_path}")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx_args = {"storage_state": str(SESSION_FILE)} if SESSION_FILE.exists() else {}
        context = browser.new_context(**ctx_args)
        page = context.new_page()
        try:
            url = f"https://app.gumroad.com/products/{permalink}/edit"
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            if not _ensure_logged_in(page, context):
                return False
            if "edit" not in page.url:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)

            # カバー画像 input を探す（複数セレクタ試行）
            cover_input = None
            for sel in [
                "input[type='file'][accept*='image']",
                "[class*='cover'] input[type='file']",
                "[class*='Cover'] input[type='file']",
                "[class*='thumbnail'] input[type='file']",
            ]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    cover_input = loc
                    break

            if cover_input is None:
                log.warning("カバー画像 input が見つからずスキップ")
                return False

            cover_input.set_input_files(image_path)
            page.wait_for_timeout(3000)

            save = page.locator(
                "button:has-text('Save changes'), button:has-text('Save'), button[type='submit']"
            ).first
            if save.count() > 0:
                save.click()
                page.wait_for_timeout(2000)

            context.storage_state(path=str(SESSION_FILE))
            log.info(f"カバー画像アップロード完了: {permalink}")
            return True
        except Exception as e:
            log.error(f"カバー画像アップロードエラー: {e}")
            return False
        finally:
            browser.close()


def upload_and_publish(product_id: str, file_path: str) -> bool:
    """製品ページにファイルをアップロードして公開。成功したら True を返す。"""
    f = Path(file_path)
    if not f.exists():
        log.error(f"ファイルが存在しません: {file_path}")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context_args = {"storage_state": str(SESSION_FILE)} if SESSION_FILE.exists() else {}
        context = browser.new_context(**context_args)
        page = context.new_page()

        try:
            page.goto("https://app.gumroad.com/dashboard", wait_until="domcontentloaded")
            page.wait_for_timeout(1500)

            if "login" in page.url or "sign_in" in page.url:
                log.info("未ログイン。ログイン中...")
                _login(page)
                SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(SESSION_FILE))

            from urllib.parse import quote
            pid_enc = quote(product_id, safe="")
            page.goto(f"https://app.gumroad.com/products/{pid_enc}/edit", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            file_input = page.locator("input[type='file']").first
            file_input.set_input_files(str(f))
            log.info(f"ファイルセット: {f.name}")
            page.wait_for_timeout(5000)

            page.locator("button[type='submit'], button:has-text('Save')").first.click()
            page.wait_for_timeout(3000)

            toggle = page.locator("input[name='published']").first
            if toggle.count() > 0 and not toggle.is_checked():
                toggle.click()
                page.wait_for_timeout(2000)

            page.locator("button[type='submit'], button:has-text('Save')").first.click()
            page.wait_for_timeout(2000)

            context.storage_state(path=str(SESSION_FILE))
            log.info(f"完了: product_id={product_id}")
            return True

        except PlaywrightTimeout as e:
            log.error(f"タイムアウト: {e}")
            page.screenshot(path=str(Path(__file__).parent / "data" / "error_screenshot.png"))
            return False
        except Exception as e:
            log.error(f"エラー: {e}")
            page.screenshot(path=str(Path(__file__).parent / "data" / "error_screenshot.png"))
            return False
        finally:
            browser.close()


def setup_session():
    """有人モードで一度だけログイン → セッション保存。以後は自動。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://app.gumroad.com/login")
        print("\nブラウザが開きました。")
        print("メール/パスワードでログインして（メール確認コードも入力）、")
        print("ダッシュボードが表示されたら Enter を押してください。")
        input(">>> Enter: ")
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_FILE))
        print("セッション保存完了。以後は完全自動で動きます。")
        browser.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="[uploader] %(asctime)s %(message)s")
    if "--setup" in sys.argv:
        setup_session()
        sys.exit(0)
    if len(sys.argv) < 3:
        print("Usage: python uploader.py <product_id> <file_path>")
        print("       python uploader.py --setup   （初回のみ）")
        sys.exit(1)
    success = upload_and_publish(sys.argv[1], sys.argv[2])
    sys.exit(0 if success else 1)
