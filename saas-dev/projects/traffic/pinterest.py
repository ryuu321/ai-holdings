"""Pinterest 自動ピン投稿 — Gumroad商品をPinterestで拡散"""
import os
import json
import logging
import time
from pathlib import Path
from dotenv import load_dotenv
from groq import Groq
from playwright.sync_api import sync_playwright

_ROOT = Path(__file__).parent.parent.parent.parent
load_dotenv(_ROOT / ".env")

GROQ_KEY       = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL     = "llama-3.3-70b-versatile"
SESSION_FILE   = Path(__file__).parent / "data" / "pinterest_session.json"
POSTED_LOG     = Path(__file__).parent / "data" / "pinterest_posted.json"

# 商品タイプ別Pinterestボード名（Pinterestで事前作成が必要）
BOARDS = {
    "ai_prompts":      "AI Prompt Packs",
    "notion_template": "Notion Templates",
    "default":         "Digital Products",
}

log = logging.getLogger(__name__)


def _generate_pin_description(title: str, niche: str, product_type: str) -> str:
    """Groqでピン用キャッシュリッチな説明文を生成。"""
    if not GROQ_KEY:
        return f"Boost your productivity as a {niche} professional. {title} — 50 ready-to-use prompts inside. Save time, work smarter. #AI #Productivity #{niche.replace(' ','')}"

    client = Groq(api_key=GROQ_KEY)
    ptype_label = "AI prompt pack" if product_type == "ai_prompts" else "Notion template"
    prompt = f"""Write a Pinterest pin description for a digital product.
Product: "{title}" — a {ptype_label} for {niche} professionals.
Requirements:
- 2-3 sentences, benefit-focused
- Include 5-8 relevant hashtags at the end
- Mention the value: saves time, boosts productivity, immediately usable
- Natural tone, not salesy
- Under 500 characters total
Output ONLY the description text, nothing else."""

    try:
        msg = client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.choices[0].message.content.strip()
    except Exception as e:
        log.warning(f"Groq説明文生成失敗: {e}")
        return f"{title} for {niche} professionals. Save time with ready-to-use templates. #AI #Productivity #DigitalTools"


def _load_posted() -> set:
    if POSTED_LOG.exists():
        try:
            return set(json.loads(POSTED_LOG.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def _save_posted(product_id: str):
    posted = _load_posted()
    posted.add(product_id)
    POSTED_LOG.parent.mkdir(parents=True, exist_ok=True)
    POSTED_LOG.write_text(json.dumps(list(posted), ensure_ascii=False), encoding="utf-8")


def _ensure_logged_in(page, context) -> bool:
    if "pinterest.com" in page.url and "login" not in page.url:
        return True
    log.error("Pinterestセッション切れ。python pinterest.py --setup を実行してください")
    return False


def pin_product(title: str, niche: str, product_type: str,
                image_path: str, gumroad_url: str, product_id: str) -> bool:
    """
    Pinterestに製品ピンを投稿。
    product_id: 重複投稿防止用（Gumroad product_id）
    """
    if not SESSION_FILE.exists():
        log.error("Pinterestセッションなし。python pinterest.py --setup を実行してください")
        return False

    if product_id and product_id in _load_posted():
        log.info(f"既にピン済みスキップ: {product_id}")
        return True

    if not Path(image_path).exists():
        log.error(f"画像が存在しない: {image_path}")
        return False

    description = _generate_pin_description(title, niche, product_type)
    board_name  = BOARDS.get(product_type, BOARDS["default"])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(SESSION_FILE))
        page    = context.new_page()
        try:
            page.goto("https://www.pinterest.com/pin-creation-tool/", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            if not _ensure_logged_in(page, context):
                return False

            # 画像アップロード
            file_input = page.locator("input[type='file']").first
            file_input.set_input_files(image_path)
            log.info("画像アップロード中...")
            page.wait_for_timeout(5000)

            # 遷移先URL（Gumroad商品ページ）
            for sel in ["[placeholder*='destination']", "[placeholder*='URL']", "[data-test-id='pin-draft-link']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.fill(gumroad_url)
                    break

            # タイトル
            for sel in ["[placeholder*='title']", "[data-test-id='pin-draft-title']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.fill(title[:100])
                    break

            # 説明文
            for sel in ["[placeholder*='description']", "[data-test-id='pin-draft-description']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.fill(description[:500])
                    break

            page.wait_for_timeout(1000)

            # ボード選択
            for sel in ["[data-test-id='board-dropdown-select-button']", "button:has-text('Choose a board')", "[aria-label*='board']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.click()
                    page.wait_for_timeout(1500)
                    break

            # ボード名を検索してクリック
            board_found = False
            for sel in [f"text={board_name}", f"[title='{board_name}']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.click()
                    board_found = True
                    break

            if not board_found:
                # 最初のボードを選択
                page.locator("[data-test-id='boardOption']").first.click()
                log.warning(f"ボード '{board_name}' が見つからず最初のボードを使用")

            page.wait_for_timeout(1000)

            # 公開ボタン
            for sel in ["[data-test-id='board-dropdown-save-button']", "button:has-text('Publish')", "button:has-text('Save')"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.click()
                    break

            page.wait_for_timeout(4000)
            context.storage_state(path=str(SESSION_FILE))

            if product_id:
                _save_posted(product_id)

            log.info(f"Pinterestピン投稿完了: {title}")
            return True

        except Exception as e:
            log.error(f"Pinterest投稿エラー: {e}")
            try:
                page.screenshot(path=str(SESSION_FILE.parent / "pin_error.png"))
            except Exception:
                pass
            return False
        finally:
            browser.close()


def setup_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page    = context.new_page()
        page.goto("https://www.pinterest.com/login/")
        print("\nブラウザでPinterestにログインしてください。")
        print("ホーム画面が表示されたら Enter を押してください。")
        input(">>> Enter: ")
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_FILE))
        print("Pinterestセッション保存完了。")
        browser.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="[pinterest] %(asctime)s %(message)s")
    if "--setup" in sys.argv:
        setup_session()
    else:
        print("Usage: python pinterest.py --setup")
