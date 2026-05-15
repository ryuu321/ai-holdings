"""
kdp_uploader.py — Kindle KDP EPUB自動アップロード
使い方: python kdp_uploader.py
セッション: KDP_SESSION_B64環境変数（base64エンコードされたJSON）

Amazon KDPのフォームをPlaywrightで操作し、
books.jsonのepub_readyな本を順番に出品する。
"""
import json
import os
import time
import base64
import logging
from pathlib import Path
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(
    level=logging.INFO,
    format="[kdp] %(asctime)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_FILE    = Path(__file__).parent / "data" / "books.json"
SESSION_FILE = Path(__file__).parent / "data" / "kdp_session.json"
KDP_URL      = "https://kdp.amazon.co.jp"

CATEGORY_MAP = {
    "投資・資産形成": ["Business & Economics", "Personal Finance"],
    "節約・家計管理": ["Business & Economics", "Personal Finance"],
    "副業・収入アップ": ["Business & Economics", "Entrepreneurship"],
    "美容・コスメ":    ["Health, Fitness & Dieting", "Beauty & Fashion"],
}

KEYWORDS_DEFAULT = ["電子書籍", "日本語", "初心者向け", "副業", "資産形成"]


def _restore_session():
    """環境変数からKDPセッションを復元する。"""
    b64 = os.environ.get("KDP_SESSION_B64", "") or os.environ.get("KDP_SESSION", "")
    if not b64:
        log.warning("KDP_SESSION_B64が未設定。セッションファイルを使用します。")
        return
    try:
        decoded = base64.b64decode(b64).decode("utf-8")
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(decoded, encoding="utf-8")
        log.info("KDPセッション復元完了")
    except Exception as e:
        log.error(f"セッション復元失敗: {e}")


def _load_books() -> list:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []


def _save_books(books: list):
    DATA_FILE.write_text(json.dumps(books, ensure_ascii=False, indent=2), encoding="utf-8")


def _upload_one(page, book: dict) -> bool:
    """1冊をKDPに出品する。成功でTrue、失敗でFalseを返す。"""
    epub_path = Path(__file__).parent / book.get("epub_path", "")
    if not epub_path.exists():
        log.error(f"EPUBが存在しない: {epub_path}")
        return False

    title    = book.get("title", "")
    subtitle = book.get("subtitle", "")
    author   = book.get("author", "D.ryu")
    desc     = book.get("description", "")
    keywords = book.get("keywords", KEYWORDS_DEFAULT)[:7]
    category = book.get("category", "投資・資産形成")

    log.info(f"出品開始: {title}")

    try:
        # ─── Step0: KDPホームへ ───
        page.goto(f"{KDP_URL}/en_US/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        # ログイン確認
        if "signin" in page.url or "login" in page.url or "ap/signin" in page.url:
            log.error("セッション切れ。手動でKDP_SESSION_B64を更新してください。")
            return False

        # ─── Step1: 新規タイトル作成ボタン ───
        create_btn = page.locator(
            "a[href*='create'], button:has-text('Create'), a:has-text('タイトルを追加'), "
            "a:has-text('Kindle eBook')"
        ).first
        if create_btn.count() == 0:
            # ダッシュボードのCreate New Titleボタン
            page.goto(f"{KDP_URL}/en_US/title-setup/kindle", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
        else:
            create_btn.click()
            page.wait_for_timeout(2000)
            # Kindle eBookを選択
            kindle_opt = page.locator("a:has-text('Kindle eBook'), button:has-text('Kindle eBook')").first
            if kindle_opt.count() > 0:
                kindle_opt.click()
                page.wait_for_timeout(2000)

        log.info("  Step1: タイトル詳細入力")

        # ─── Step1: Book Details ───
        # 言語
        for sel in ["select[id*='language']", "#language", "select[name*='language']"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                try:
                    loc.select_option("ja")
                    break
                except Exception:
                    pass

        # タイトル
        for sel in ["input[id*='book-title']", "input[name*='title']", "#book-title"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.fill(title)
                break

        # サブタイトル
        if subtitle:
            for sel in ["input[id*='subtitle']", "input[name*='subtitle']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.fill(subtitle)
                    break

        # 著者
        for sel in ["input[id*='author-first-name']", "input[name*='authorFirstName']"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.fill(author)
                # 姓フィールド
                page.locator("input[id*='author-last-name'], input[name*='authorLastName']").first.fill("")
                break

        # 説明（内容紹介）
        for sel in ["textarea[id*='description']", "#book-description", "textarea[name*='description']"]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                loc.fill(desc[:4000])
                break

        # キーワード（7個まで）
        for i, kw in enumerate(keywords[:7]):
            for sel in [f"input[id*='keyword-{i}']", f"input[id*='keywords-{i}']",
                        f"input[name*='keyword'][data-index='{i}']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.fill(kw)
                    break

        page.wait_for_timeout(1000)

        # 「次へ」ボタン
        next_btn = page.locator("button:has-text('Save and Continue'), button:has-text('次へ'), "
                                "input[value*='Save'], button[type='submit']").first
        if next_btn.count() > 0:
            next_btn.click()
            page.wait_for_timeout(3000)

        log.info("  Step2: EPUB/コンテンツアップロード")

        # ─── Step2: Content ───
        # DRM無効化（自由に読めるほうがレビューが増えやすい）
        no_drm = page.locator("input[value='no-drm'], label:has-text('DRM無し'), "
                              "input[id*='noDrm']").first
        if no_drm.count() > 0:
            no_drm.click()

        # EPUBアップロード
        file_input = page.locator("input[type='file'][accept*='.epub'], "
                                  "input[type='file'][accept*='epub']").first
        if file_input.count() == 0:
            file_input = page.locator("input[type='file']").first

        if file_input.count() > 0:
            file_input.set_input_files(str(epub_path))
            log.info(f"  EPUBセット: {epub_path.name}")
            # アップロード完了を最大3分待つ
            for _ in range(36):
                page.wait_for_timeout(5000)
                uploading = page.locator("[class*='uploading'], [class*='processing'], "
                                        "span:has-text('Uploading'), span:has-text('Processing')")
                if uploading.count() == 0:
                    break
            log.info("  EPUBアップロード完了")
        else:
            log.warning("  ファイルinputが見つかりません（スキップ）")

        # 表紙画像
        cover_path = epub_path.parent / "cover.jpg"
        if cover_path.exists():
            cover_input = page.locator("input[type='file'][accept*='image']").first
            if cover_input.count() > 0:
                cover_input.set_input_files(str(cover_path))
                page.wait_for_timeout(3000)
                log.info("  表紙アップロード完了")

        # 次へ
        next_btn2 = page.locator("button:has-text('Save and Continue'), button:has-text('次へ'), "
                                 "button[type='submit']").first
        if next_btn2.count() > 0:
            next_btn2.click()
            page.wait_for_timeout(3000)

        log.info("  Step3: 価格設定")

        # ─── Step3: Pricing ───
        # 領土：全世界
        all_territories = page.locator("input[value='WORLD'], label:has-text('All territories')").first
        if all_territories.count() > 0:
            all_territories.click()

        # KDPセレクト: 加入しない（任意、加入すると独占配信になる）
        # デフォルトで非加入のためスキップ

        # 日本価格（¥980）
        jp_price = page.locator(
            "input[id*='JP'], input[id*='Japan'], input[name*='JP'], "
            "input[id*='price-JP']"
        ).first
        if jp_price.count() > 0:
            jp_price.fill("980")
            page.wait_for_timeout(500)

        # 印税70%（要件: ¥250-¥5,000、条件を満たす場合のみ）
        royalty_70 = page.locator(
            "input[value='70'], label:has-text('70%'), input[id*='royalty70']"
        ).first
        if royalty_70.count() > 0:
            royalty_70.click()

        page.wait_for_timeout(1000)

        # 出版（Publish）
        publish_btn = page.locator(
            "button:has-text('Publish'), button:has-text('出版する'), "
            "input[value='Publish'], button[id*='publish']"
        ).first
        if publish_btn.count() > 0:
            publish_btn.click()
            page.wait_for_timeout(5000)
            log.info(f"  ✅ 出版申請完了: {title}")
            return True
        else:
            # 保存のみ（出版ボタンが見つからない場合）
            save_btn = page.locator("button:has-text('Save'), button[type='submit']").first
            if save_btn.count() > 0:
                save_btn.click()
                page.wait_for_timeout(3000)
            log.warning("  出版ボタンが見つかりません。ダッシュボードから確認してください。")
            return False

    except PlaywrightTimeout as e:
        log.error(f"タイムアウト: {e}")
        try:
            page.screenshot(path=str(DATA_FILE.parent / "kdp_error.png"))
        except Exception:
            pass
        return False
    except Exception as e:
        log.error(f"エラー: {e}")
        try:
            page.screenshot(path=str(DATA_FILE.parent / "kdp_error.png"))
        except Exception:
            pass
        return False


def run():
    _restore_session()

    if not SESSION_FILE.exists():
        log.error("KDPセッションファイルが存在しません。")
        log.error("初回は手動でログインしてセッションを保存してください:")
        log.error("  python kdp_uploader.py --setup")
        return

    books = _load_books()
    pending = [b for b in books if b.get("status") == "epub_ready"]

    if not pending:
        log.info("アップロード待ちの本はありません。")
        return

    log.info(f"アップロード待ち: {len(pending)}冊")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            storage_state=str(SESSION_FILE),
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        page = context.new_page()

        success_count = 0
        for book in pending:
            ok = _upload_one(page, book)
            if ok:
                # books.jsonを更新
                for b in books:
                    if b.get("title") == book.get("title"):
                        b["status"] = "published"
                        b["published_at"] = datetime.now(timezone.utc).isoformat()
                        b["price_jpy"] = 980
                        break
                _save_books(books)
                success_count += 1
            else:
                log.warning(f"スキップ: {book.get('title')}")

            # インターバル（Amazon対策）
            time.sleep(10)

        # セッション保存
        context.storage_state(path=str(SESSION_FILE))
        browser.close()

    log.info(f"\n完了: {success_count}/{len(pending)}冊 出版申請")
    if success_count > 0:
        log.info("KDPダッシュボードで審査状況を確認してください（通常72時間以内）")


def setup_session():
    """有人モードで一度だけログイン → セッション保存。"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{KDP_URL}/en_US/")
        print("\nブラウザが開きました。KDPにログインしてください（2FA含む）。")
        print("ダッシュボードが表示されたら Enter を押してください。")
        input(">>> Enter: ")
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_FILE))

        # base64でエンコードして表示（GitHubシークレット用）
        encoded = base64.b64encode(SESSION_FILE.read_bytes()).decode()
        print(f"\n✅ セッション保存完了: {SESSION_FILE}")
        print(f"\n以下をGitHub Secrets の KDP_SESSION_B64 に登録してください:")
        print(f"  (コピー用ファイル: data/kdp_session_b64.txt)")
        (SESSION_FILE.parent / "kdp_session_b64.txt").write_text(encoded)
        browser.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="[kdp] %(asctime)s %(message)s")
    if "--setup" in sys.argv:
        setup_session()
    else:
        run()
