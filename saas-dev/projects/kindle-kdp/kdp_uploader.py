"""
kdp_uploader.py — Kindle KDP EPUB自動アップロード

セッション管理:
  1. KDP_SESSION / KDP_SESSION_B64: 保存済みセッション（優先使用）
  2. セッション切れ → KDP_EMAIL + KDP_PASSWORD で自動再ログイン
  3. Amazon 2FA → 別ブラウザページでGmailを開いてOTPを自動取得
     （App Password不要・KDP_EMAIL + KDP_PASSWORD だけで完結）
"""
import json
import os
import re
import time
import base64
import logging
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger(__name__)

DATA_FILE    = Path(__file__).parent / "data" / "books.json"
SESSION_FILE = Path(__file__).parent / "data" / "kdp_session.json"
KDP_URL      = "https://kdp.amazon.co.jp"

KDP_EMAIL    = os.environ.get("KDP_EMAIL", "")
KDP_PASSWORD = os.environ.get("KDP_PASSWORD", "")
KEYWORDS_DEFAULT = ["電子書籍", "日本語", "初心者向け", "副業", "資産形成"]


# ─────────────────────── セッション管理 ───────────────────────

def _restore_session():
    """環境変数からセッションファイルを復元する。
    KDP_SESSION_B64（base64）またはKDP_SESSION（JSON文字列）を試みる。"""
    for key in ("KDP_SESSION_B64", "KDP_SESSION"):
        raw = os.environ.get(key, "")
        if not raw:
            continue
        try:
            # base64かJSONか判定
            if raw.strip().startswith("{"):
                decoded = raw  # すでにJSONテキスト
            else:
                decoded = base64.b64decode(raw).decode("utf-8")
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_FILE.write_text(decoded, encoding="utf-8")
            log.info(f"KDPセッション復元完了（{key}）")
            return
        except Exception as e:
            log.debug(f"{key} 復元失敗: {e}")


def _save_session(context):
    """Playwrightコンテキストからセッションを保存し、base64も出力する。"""
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(SESSION_FILE))
    encoded = base64.b64encode(SESSION_FILE.read_bytes()).decode()
    out = SESSION_FILE.parent / "kdp_session_b64.txt"
    out.write_text(encoded)
    log.info(f"セッション保存完了 → {out}")
    log.info("GitHub Secrets の KDP_SESSION_B64 にこのファイルの内容を登録してください")


# ─────────────────────── Gmail OTP取得（Playwright） ───────────────────────

def _fetch_otp_via_gmail_browser(browser, timeout_sec: int = 90) -> str:
    """
    Playwrightで新しいブラウザページを開いてGmailにログインし、
    Amazonからのワンタイムパスコードを取得する。
    App Password不要・メール/パスワードだけで完結。
    """
    if not KDP_EMAIL or not KDP_PASSWORD:
        log.warning("KDP_EMAIL / KDP_PASSWORD 未設定のためOTP取得不可")
        return ""

    log.info("Gmail ブラウザログインでOTPを取得中...")

    gmail_page = browser.new_page()
    try:
        # Gmailにログイン
        gmail_page.goto("https://accounts.google.com/signin/v2/identifier"
                        "?service=mail&continue=https://mail.google.com/",
                        wait_until="domcontentloaded", timeout=20000)
        gmail_page.wait_for_timeout(1500)

        # メールアドレス入力
        gmail_page.locator("input[type='email'], #identifierId").first.fill(KDP_EMAIL)
        gmail_page.locator("button:has-text('次へ'), #identifierNext button").first.click()
        gmail_page.wait_for_timeout(2000)

        # パスワード入力
        gmail_page.locator("input[type='password'], #password input").first.fill(KDP_PASSWORD)
        gmail_page.locator("button:has-text('次へ'), #passwordNext button").first.click()
        gmail_page.wait_for_timeout(3000)

        # 2FA ページが出たらスキップ（電話番号確認など）
        for skip_sel in [
            "button:has-text('後で行う')", "button:has-text('Skip')",
            "button:has-text('今はしない')", "[data-action='skip']",
        ]:
            btn = gmail_page.locator(skip_sel).first
            if btn.count() > 0:
                btn.click()
                gmail_page.wait_for_timeout(1000)

        # 受信トレイが開くまで待つ
        deadline = time.time() + timeout_sec
        otp = ""
        while time.time() < deadline:
            gmail_page.wait_for_timeout(8000)

            # 「Amazon」から来た未読メールを検索
            try:
                gmail_page.goto(
                    "https://mail.google.com/mail/u/0/#search/from%3Aamazon+is%3Aunread",
                    wait_until="domcontentloaded", timeout=15000
                )
                gmail_page.wait_for_timeout(3000)

                # 最初のメールをクリック
                first_mail = gmail_page.locator(
                    "tr.zA, [data-legacy-message-id], .zA"
                ).first
                if first_mail.count() == 0:
                    log.debug("Amazonの未読メールなし、リトライ...")
                    continue

                first_mail.click()
                gmail_page.wait_for_timeout(2000)

                # メール本文から6桁コードを抽出
                body = gmail_page.inner_text("body")
                m = re.search(r'\b(\d{6})\b', body)
                if m:
                    otp = m.group(1)
                    log.info(f"Gmail OTP取得成功: {otp[:2]}****")
                    break
            except Exception as e:
                log.debug(f"Gmail OTP取得リトライ: {e}")

        return otp

    except Exception as e:
        log.error(f"Gmail OTP取得エラー: {e}")
        return ""
    finally:
        try:
            gmail_page.close()
        except Exception:
            pass


# ─────────────────────── 自動ログイン ───────────────────────

def _auto_login(page, context, browser) -> bool:
    """
    Amazon KDPにメール/パスワードで自動ログインする。
    2FAが必要な場合はPlaywright Gmailブラウザでワンタイムパスを自動取得して入力する。
    成功したらセッションを保存してTrueを返す。
    """
    if not KDP_EMAIL or not KDP_PASSWORD:
        log.error("自動ログイン不可: KDP_EMAIL / KDP_PASSWORD が未設定")
        return False

    log.info("セッション切れ → 自動ログイン開始")

    try:
        page.goto("https://www.amazon.co.jp/ap/signin?openid.pape.max_auth_age=0"
                  "&openid.ns=http://specs.openid.net/auth/2.0"
                  "&openid.mode=checkid_setup"
                  "&openid.return_to=https://kdp.amazon.co.jp/en_US/",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        # メールアドレス入力
        email_input = page.locator("input[name='email'], input[type='email'], #ap_email").first
        if email_input.count() == 0:
            log.error("メールフィールドが見つかりません")
            return False
        email_input.fill(KDP_EMAIL)

        # 「次へ」クリック
        for btn_sel in ["input[id='continue']", "input[type='submit']", "button[type='submit']"]:
            btn = page.locator(btn_sel).first
            if btn.count() > 0:
                btn.click()
                break
        page.wait_for_timeout(2000)

        # パスワード入力
        pw_input = page.locator("input[name='password'], input[type='password'], #ap_password").first
        if pw_input.count() > 0:
            pw_input.fill(KDP_PASSWORD)

        # サインインボタン
        for btn_sel in ["input[id='signInSubmit']", "input[type='submit']", "button[type='submit']"]:
            btn = page.locator(btn_sel).first
            if btn.count() > 0:
                btn.click()
                break
        page.wait_for_timeout(3000)

        # ─── 2FA処理 ───
        url = page.url
        is_2fa = any(k in url for k in ["auth-mfa", "two-step", "verification", "claimspicker"])
        otp_field = page.locator(
            "input[name='otpCode'], input[id='auth-mfa-otpcode'], "
            "input[placeholder*='OTP'], input[placeholder*='コード']"
        ).first

        if is_2fa or otp_field.count() > 0:
            log.info("2FA画面を検出 → GmailブラウザでOTPを取得中...")
            otp = _fetch_otp_via_gmail_browser(browser)
            if not otp:
                log.error("OTP取得失敗。KDP_EMAIL / KDP_PASSWORDを確認してください。")
                return False

            otp_field.fill(otp)
            page.wait_for_timeout(500)

            # 「このデバイスを信頼する」にチェック（次回2FAをスキップ）
            for trust_sel in [
                "input[name='rememberDevice']",
                "input[id='auth-mfa-remember-device']",
                "label:has-text('このデバイスを記憶する')",
            ]:
                trust = page.locator(trust_sel).first
                if trust.count() > 0:
                    trust.check()
                    break

            # OTP送信
            for btn_sel in ["input[id='auth-signin-button']", "input[type='submit']", "button[type='submit']"]:
                btn = page.locator(btn_sel).first
                if btn.count() > 0:
                    btn.click()
                    break
            page.wait_for_timeout(4000)

        # ─── ログイン成功確認 ───
        if "signin" in page.url or "login" in page.url or "ap/signin" in page.url:
            log.error(f"ログイン失敗。現在URL: {page.url}")
            return False

        # KDPへリダイレクト
        if "kdp.amazon" not in page.url:
            page.goto(f"{KDP_URL}/en_US/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

        _save_session(context)
        log.info("自動ログイン成功 ✅")
        return True

    except Exception as e:
        log.error(f"自動ログインエラー: {e}")
        return False


# ─────────────────────── ログイン確認 ───────────────────────

def _ensure_logged_in(page, context, browser) -> bool:
    """現在ページがログイン済みか確認し、切れていれば自動再ログインする。"""
    url = page.url
    if not any(k in url for k in ["signin", "login", "ap/signin", "auth"]):
        return True  # ログイン済み

    log.info("セッション切れを検出")
    return _auto_login(page, context, browser)


# ─────────────────────── 1冊アップロード ───────────────────────

def _upload_one(page, context, browser, book: dict) -> bool:
    """1冊をKDPに出品する。セッション切れは自動で回復する。"""
    epub_path = Path(__file__).parent / book.get("epub_path", "")
    if not epub_path.exists():
        log.error(f"EPUBが存在しない: {epub_path}")
        return False

    title    = book.get("title", "")
    subtitle = book.get("subtitle", "")
    author   = book.get("author", "D.ryu")
    desc     = book.get("description", "")
    keywords = book.get("keywords", KEYWORDS_DEFAULT)[:7]

    log.info(f"出品開始: 『{title[:40]}』")

    try:
        # ─── KDPダッシュボードへ ───
        page.goto(f"{KDP_URL}/en_US/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        if not _ensure_logged_in(page, context, browser):
            return False

        # ─── Step1: 新規タイトル作成 ───
        page.goto(f"{KDP_URL}/en_US/title-setup/kindle",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        if not _ensure_logged_in(page, context, browser):
            return False

        log.info("  [1/3] タイトル・著者・説明を入力中...")

        # 言語: 日本語
        for sel in ["select[id*='language']", "#language"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                try:
                    loc.select_option("ja")
                except Exception:
                    pass
                break

        # タイトル
        for sel in ["input[id*='book-title']", "#book-title", "input[name*='title']"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.clear()
                loc.fill(title)
                break

        # サブタイトル
        if subtitle:
            for sel in ["input[id*='subtitle']", "input[name*='subtitle']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.clear()
                    loc.fill(subtitle)
                    break

        # 著者名（名・姓）
        for sel in ["input[id*='author-first-name']"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.fill(author)
                page.locator("input[id*='author-last-name']").first.fill("")
                break

        # 説明
        for sel in ["textarea[id*='description']", "#book-description"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.fill(desc[:4000])
                break

        # キーワード（最大7個）
        for i, kw in enumerate(keywords):
            for sel in [f"input[id*='keyword-{i}']", f"input[id*='keywords'][data-index='{i}']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.fill(kw)
                    break

        page.wait_for_timeout(1000)

        # 「保存して続行」
        _click_next(page)
        page.wait_for_timeout(3000)

        # ─── Step2: コンテンツ（EPUB + 表紙） ───
        log.info("  [2/3] EPUBをアップロード中...")

        file_input = page.locator(
            "input[type='file'][accept*='.epub'], input[type='file'][accept*='epub']"
        ).first
        if file_input.count() == 0:
            file_input = page.locator("input[type='file']").first

        if file_input.count() > 0:
            file_input.set_input_files(str(epub_path))
            # アップロード完了を最大3分待つ
            for _ in range(36):
                page.wait_for_timeout(5000)
                still_uploading = page.locator(
                    "[class*='uploading'], [class*='processing'], "
                    "span:has-text('Uploading'), span:has-text('変換中')"
                ).count()
                if not still_uploading:
                    break
            log.info("  EPUB完了")
        else:
            log.warning("  ファイルinputが見つかりません")

        # 表紙
        cover_path = epub_path.parent / "cover.jpg"
        if cover_path.exists():
            cover_input = page.locator("input[type='file'][accept*='image']").first
            if cover_input.count() > 0:
                cover_input.set_input_files(str(cover_path))
                page.wait_for_timeout(3000)

        _click_next(page)
        page.wait_for_timeout(3000)

        # ─── Step3: 価格設定 ───
        log.info("  [3/3] 価格設定（¥980 / 70%印税）...")

        # 全世界配信
        for sel in ["input[value='WORLD']", "label:has-text('All territories')"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click()
                break

        # 70%印税プラン
        for sel in ["input[value='70']", "label:has-text('70%')", "input[id*='royalty70']"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.click()
                page.wait_for_timeout(500)
                break

        # 日本円価格
        for sel in ["input[id*='JP']", "input[id*='Japan']", "input[name*='price-JP']"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.fill("980")
                page.keyboard.press("Tab")  # 他通貨への自動換算をトリガー
                page.wait_for_timeout(1000)
                break

        page.wait_for_timeout(1000)

        # 出版ボタン
        publish_btn = page.locator(
            "button:has-text('Publish'), button:has-text('出版する'), "
            "button:has-text('公開する'), input[value='Publish']"
        ).first
        if publish_btn.count() > 0:
            publish_btn.click()
            page.wait_for_timeout(5000)
            log.info(f"  ✅ 出版申請完了: 『{title[:40]}』")
            _save_session(context)
            return True
        else:
            _click_next(page)
            page.wait_for_timeout(3000)
            log.warning("  出版ボタンが見つかりませんでした（ダッシュボードで確認してください）")
            return False

    except PlaywrightTimeout as e:
        log.error(f"タイムアウト: {e}")
        _screenshot(page)
        return False
    except Exception as e:
        log.error(f"エラー: {e}")
        _screenshot(page)
        return False


def _click_next(page):
    """次へ / Save and Continue ボタンをクリックする。"""
    for sel in [
        "button:has-text('Save and continue')",
        "button:has-text('次へ')",
        "button:has-text('保存して続行')",
        "input[value*='Save']",
        "button[type='submit']",
    ]:
        btn = page.locator(sel).first
        if btn.count() > 0:
            btn.click()
            return


def _screenshot(page):
    try:
        path = DATA_FILE.parent / "kdp_error.png"
        page.screenshot(path=str(path))
        log.info(f"エラースクリーンショット: {path}")
    except Exception:
        pass


# ─────────────────────── メイン ───────────────────────

def _load_books() -> list:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []


def _save_books(books: list):
    DATA_FILE.write_text(json.dumps(books, ensure_ascii=False, indent=2), encoding="utf-8")


def run():
    logging.basicConfig(
        level=logging.INFO,
        format="[kdp] %(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )

    _restore_session()

    books   = _load_books()
    pending = [b for b in books if b.get("status") == "epub_ready"]

    if not pending:
        log.info("アップロード待ちの本はありません。")
        return

    log.info(f"アップロード待ち: {len(pending)}冊")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx_args = {"locale": "ja-JP", "timezone_id": "Asia/Tokyo"}
        if SESSION_FILE.exists():
            ctx_args["storage_state"] = str(SESSION_FILE)

        context = browser.new_context(**ctx_args)
        page    = context.new_page()

        # セッションがない場合は初回ログインを試みる
        if not SESSION_FILE.exists():
            log.info("保存済みセッションなし → 初回ログイン")
            if not _auto_login(page, context, browser):
                log.error("ログイン失敗。処理を中断します。")
                browser.close()
                return

        success_count = 0
        for book in pending:
            ok = _upload_one(page, context, browser, book)
            if ok:
                for b in books:
                    if b.get("title") == book.get("title"):
                        b["status"]       = "published"
                        b["published_at"] = datetime.now(timezone.utc).isoformat()
                        b["price_jpy"]    = 980
                        break
                _save_books(books)
                success_count += 1
            else:
                log.warning(f"スキップ: {book.get('title')}")

            time.sleep(15)  # Amazon対策インターバル

        browser.close()

    log.info(f"\n完了: {success_count}/{len(pending)}冊 出版申請")
    if success_count > 0:
        log.info("KDPダッシュボードで審査状況を確認してください（通常72時間以内）")


def setup_session():
    """初回のみ: 有人モードでログインしてセッション保存。"""
    logging.basicConfig(level=logging.INFO, format="[kdp] %(asctime)s %(message)s")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page    = context.new_page()
        page.goto(f"{KDP_URL}/en_US/")
        print("\nブラウザが開きました。KDPにログインしてください（2FA含む）。")
        print("ダッシュボードが表示されたら Enter を押してください。")
        input(">>> Enter: ")
        _save_session(context)
        print(f"\n✅ KDP_SESSION_B64 をGitHub Secretsに登録してください:")
        print(f"   ファイル: {SESSION_FILE.parent}/kdp_session_b64.txt")
        browser.close()


if __name__ == "__main__":
    import sys
    if "--setup" in sys.argv:
        setup_session()
    else:
        run()
