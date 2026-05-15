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


def _fetch_gumroad_products() -> list[dict]:
    """Gumroad APIから公開済み商品一覧を取得。"""
    import requests
    token = os.environ.get("GUMROAD_ACCESS_TOKEN", "")
    if not token:
        log.warning("GUMROAD_ACCESS_TOKEN未設定")
        return []
    try:
        r = requests.get(
            "https://api.gumroad.com/v2/products",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        r.raise_for_status()
        return [p for p in r.json().get("products", []) if p.get("published")]
    except Exception as e:
        log.warning(f"Gumroad商品取得失敗: {e}")
        return []


def _make_thumbnail(title: str, product_type: str, out_path: Path) -> bool:
    """Pillowで1000×1500 Pinterestサイズのサムネイルを生成。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        W, H = 1000, 1500
        is_prompts = "prompt" in product_type.lower() or "ai" in title.lower()
        bg     = (12, 20, 55)    if is_prompts else (25, 12, 45)
        accent = (56, 139, 253)  if is_prompts else (130, 80, 255)
        img    = Image.new("RGB", (W, H), bg)
        draw   = ImageDraw.Draw(img)
        # グラデーション背景
        for i in range(400):
            t = i / 400
            r = int(bg[0] * (1 - t * 0.5))
            g = int(bg[1] * (1 - t * 0.5))
            b = int(bg[2] + (255 - bg[2]) * t * 0.1)
            draw.line([(0, i), (W, i)], fill=(r, g, b))
        # アクセントバー
        draw.rectangle([0, 0, 12, H], fill=accent)
        draw.rectangle([0, H - 12, W, H], fill=accent)
        # フォント
        font_cands = [
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 72),
            ("C:/Windows/Fonts/arialbd.ttf", 72),
        ]
        sub_cands = [
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 42),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 42),
            ("C:/Windows/Fonts/arial.ttf", 42),
        ]
        font_lg = ImageFont.load_default()
        font_sm = ImageFont.load_default()
        for fp, sz in font_cands:
            if Path(fp).exists():
                try: font_lg = ImageFont.truetype(fp, sz); break
                except Exception: pass
        for fp, sz in sub_cands:
            if Path(fp).exists():
                try: font_sm = ImageFont.truetype(fp, sz); break
                except Exception: pass
        # タイトル（20文字/行で折り返し）
        words = title.split()
        lines, cur = [], []
        for w in words:
            cur.append(w)
            if len(" ".join(cur)) > 18:
                lines.append(" ".join(cur[:-1])) if len(cur) > 1 else lines.append(" ".join(cur))
                cur = [w] if len(cur) > 1 else []
        if cur: lines.append(" ".join(cur))
        lh = 90
        y = (H - len(lines) * lh - 120) // 2
        for line in lines:
            bb = draw.textbbox((0, 0), line, font=font_lg)
            tw = bb[2] - bb[0]
            draw.text(((W - tw) // 2, y), line, fill=(255, 255, 255), font=font_lg)
            y += lh
        # バッジ
        badge = "✨ AI Prompt Pack — 50 Prompts" if is_prompts else "📋 Notion Template"
        bb = draw.textbbox((0, 0), badge, font=font_sm)
        tw = bb[2] - bb[0]
        draw.text(((W - tw) // 2, H - 120), badge, fill=accent, font=font_sm)
        price_lbl = "⬇ Get it on Gumroad"
        bb2 = draw.textbbox((0, 0), price_lbl, font=font_sm)
        tw2 = bb2[2] - bb2[0]
        draw.text(((W - tw2) // 2, H - 70), price_lbl, fill=(200, 200, 200), font=font_sm)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path), "PNG")
        return True
    except Exception as e:
        log.warning(f"サムネイル生成失敗: {e}")
        return False


def run_daily(max_pins: int = 5):
    """未ピンのGumroad商品をPinterestにピン投稿する。"""
    products = _fetch_gumroad_products()
    if not products:
        log.warning("Gumroad商品なし → スキップ")
        return 0

    posted = _load_posted()
    pending = [p for p in products if p.get("id", "") not in posted]
    log.info(f"未ピン商品: {len(pending)}/{len(products)}件")

    success = 0
    for p in pending[:max_pins]:
        pid   = p.get("id", "")
        name  = p.get("name", "")
        url   = p.get("short_url", "")
        ptype = "ai_prompts" if any(w in name.lower() for w in ["prompt", "ai", "gpt"]) else "notion_template"

        thumb = Path(__file__).parent / "data" / "thumbnails" / f"pin_{pid[:8]}.png"
        if not _make_thumbnail(name, ptype, thumb):
            log.warning(f"サムネイル失敗: {name}")
            continue

        niche = name  # 商品名をnicheとして使う
        ok = pin_product(
            title=name,
            niche=niche,
            product_type=ptype,
            image_path=str(thumb),
            gumroad_url=url,
            product_id=pid,
        )
        if ok:
            success += 1
            log.info(f"ピン完了 ({success}): {name}")
            time.sleep(30)
        else:
            log.warning(f"ピン失敗: {name}")

    log.info(f"Pinterest daily完了: {success}/{len(pending[:max_pins])}件")
    return success


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="[pinterest] %(asctime)s %(message)s")
    if "--setup" in sys.argv:
        setup_session()
    elif "--daily" in sys.argv:
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        run_daily(max_pins=n)
    else:
        print("Usage: python pinterest.py --setup | --daily [N]")
