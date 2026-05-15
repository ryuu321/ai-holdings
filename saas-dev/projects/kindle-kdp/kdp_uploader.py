"""
kdp_uploader.py — Kindle KDP EPUB自動アップロード

セッション管理:
  1. KDP_SESSION_B64: 保存済みセッション（優先使用）
  2. セッション切れ → KDP_EMAIL + KDP_PASSWORD で自動再ログイン
  3. Amazon 2FA → KDP_EMAIL_APP_PASSWORD (Gmail App Password) で
     IMAP経由のOTPを自動取得して入力
"""
import json
import os
import re
import time
import base64
import imaplib
import email as email_lib
import logging
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger(__name__)

DATA_FILE    = Path(__file__).parent / "data" / "books.json"
SESSION_FILE = Path(__file__).parent / "data" / "kdp_session.json"
KDP_URL      = "https://kdp.amazon.co.jp"

KDP_EMAIL        = os.environ.get("KDP_EMAIL", "")
KDP_PASSWORD     = os.environ.get("KDP_PASSWORD", "")
EMAIL_APP_PASS   = os.environ.get("KDP_EMAIL_APP_PASSWORD", "")  # Gmail App Password
KEYWORDS_DEFAULT = ["電子書籍", "日本語", "初心者向け", "副業", "資産形成"]


# ─────────────────────── セッション管理 ───────────────────────

def _restore_session():
    """環境変数 KDP_SESSION_B64 からセッションファイルを復元する。"""
    b64 = os.environ.get("KDP_SESSION_B64", "")
    if not b64:
        return
    try:
        decoded = base64.b64decode(b64).decode("utf-8")
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(decoded, encoding="utf-8")
        log.info("KDPセッション復元完了")
    except Exception as e:
        log.warning(f"セッション復元失敗: {e}")


def _save_session(context):
    """現在のPlaywrightコンテキストからセッションを保存する。"""
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(SESSION_FILE))
    encoded = base64.b64encode(SESSION_FILE.read_bytes()).decode()
    (SESSION_FILE.parent / "kdp_session_b64.txt").write_text(encoded)
    log.info("セッション保存完了（data/kdp_session_b64.txt にbase64を出力）")


# ─────────────────────── IMAP OTP取得 ───────────────────────

def _fetch_amazon_otp(gmail_addr: str, app_password: str, timeout_sec: int = 90) -> str:
    """
    Gmail IMAPでAmazonからのワンタイムパスコードを取得する。
    timeout_sec秒以内にメールが来なければ空文字を返す。
    """
    if not gmail_addr or not app_password:
        log.warning("Gmail認証情報未設定（KDP_EMAIL / KDP_EMAIL_APP_PASSWORD）")
        return ""

    log.info(f"IMAP: Amazonのワンタイムパスコードを待機中（最大{timeout_sec}秒）...")
    deadline = time.time() + timeout_sec

    while time.time() < deadline:
        try:
            with imaplib.IMAP4_SSL("imap.gmail.com", timeout=15) as imap:
                imap.login(gmail_addr, app_password)
                imap.select("INBOX")

                # Amazonからの最近の未読メールを検索
                _, msgs = imap.search(None, 'FROM "amazon" UNSEEN')
                ids = msgs[0].split() if msgs[0] else []

                for mid in reversed(ids[-5:]):  # 最新5件を新しい順に確認
                    _, data = imap.fetch(mid, "(RFC822)")
                    raw = data[0][1] if data and data[0] else b""
                    msg = email_lib.message_from_bytes(raw)

                    # メール本文を取得
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            ct = part.get_content_type()
                            if ct in ("text/plain", "text/html"):
                                try:
                                    body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                except Exception:
                                    pass
                    else:
                        try:
                            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except Exception:
                            pass

                    # 6桁のOTPを抽出
                    m = re.search(r'\b(\d{6})\b', body)
                    if m:
                        otp = m.group(1)
                        log.info(f"OTP取得成功: {otp[:2]}****")
                        # 既読にマーク
                        imap.store(mid, "+FLAGS", "\\Seen")
                        return otp

        except Exception as e:
            log.debug(f"IMAP接続失敗（リトライ）: {e}")

        time.sleep(10)

    log.error("OTP取得タイムアウト")
    return ""


# ─────────────────────── 自動ログイン ───────────────────────

def _auto_login(page, context) -> bool:
    """
    Amazon KDPにメール/パスワードで自動ログインする。
    2FAが必要な場合はGmail IMAPでOTPを自動取得して入力する。
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
            log.info("2FA画面を検出 → OTPをGmail IMAPで取得中...")
            otp = _fetch_amazon_otp(KDP_EMAIL, EMAIL_APP_PASS)
            if not otp:
                log.error("OTP取得失敗。KDP_EMAIL_APP_PASSWORDを確認してください。")
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

def _ensure_logged_in(page, context) -> bool:
    """
    現在ページがログイン済みか確認し、切れていれば自動再ログインする。
    """
    url = page.url
    if not any(k in url for k in ["signin", "login", "ap/signin", "auth"]):
        return True  # ログイン済み

    log.info("セッション切れを検出")
    return _auto_login(page, context)


# ─────────────────────── 1冊アップロード ───────────────────────

def _upload_one(page, context, book: dict) -> bool:
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

        if not _ensure_logged_in(page, context):
            return False

        # ─── Step1: 新規タイトル作成 ───
        page.goto(f"{KDP_URL}/en_US/title-setup/kindle",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        if not _ensure_logged_in(page, context):
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
            if not _auto_login(page, context):
                log.error("ログイン失敗。処理を中断します。")
                browser.close()
                return

        success_count = 0
        for book in pending:
            ok = _upload_one(page, context, book)
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
