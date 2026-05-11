"""Twitter/X 自動投稿 — AIティップス日次投稿でGumroad集客"""
import os
import json
import logging
import random
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq
from playwright.sync_api import sync_playwright

_ROOT = Path(__file__).parent.parent.parent.parent
load_dotenv(_ROOT / ".env")

GROQ_KEY     = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL   = "llama-3.3-70b-versatile"
SESSION_FILE = Path(__file__).parent / "data" / "twitter_session.json"
POST_LOG     = Path(__file__).parent / "data" / "twitter_posted.json"

# Gumroadの商品情報（strategy.jsonから読む）
GUMROAD_STRATEGY = Path(__file__).parent.parent / "gumroad" / "data" / "strategy.json"
GUMROAD_PRODUCTS = Path(__file__).parent.parent / "gumroad" / "data" / "products"

log = logging.getLogger(__name__)


def _load_active_niches() -> list[str]:
    """strategy.jsonから直近のnicheを取得。なければデフォルト。"""
    defaults = ["Content Creators", "ADHD Productivity", "Solopreneurs"]
    try:
        if GUMROAD_STRATEGY.exists():
            data = json.loads(GUMROAD_STRATEGY.read_text(encoding="utf-8"))
            recent = data.get("used_niches_recent", [])
            if recent:
                return list(dict.fromkeys(reversed(recent)))[:3]  # 直近3ニッチ（重複除去）
    except Exception:
        pass
    return defaults


def _load_products() -> list[dict]:
    """出品済み商品の情報を取得。"""
    products = []
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "gumroad"))
        from pipeline import GUMROAD_API, GUMROAD_TOKEN
        import requests
        if GUMROAD_TOKEN:
            r = requests.get(f"{GUMROAD_API}/products",
                             headers={"Authorization": f"Bearer {GUMROAD_TOKEN}"}, timeout=10)
            products = [p for p in r.json().get("products", []) if p.get("published")]
    except Exception:
        pass
    return products


def generate_tip_tweet(niche: str, product_url: str = "") -> str:
    """Groqでニッチ向けAIティップスtweetを生成。"""
    if not GROQ_KEY:
        return f"Quick tip for {niche}: Use AI to automate your workflow. What takes 2 hours can take 20 minutes. #AI #Productivity"

    cta = f"\n\n🔗 Full prompt pack: {product_url}" if product_url else ""
    client = Groq(api_key=GROQ_KEY)

    tweet_angles = [
        f"a practical AI tip that {niche} can use today to save time",
        f"a common mistake {niche} make that AI can fix",
        f"a ChatGPT prompt that {niche} will find immediately useful",
        f"a surprising way {niche} are using AI to grow their business",
    ]
    angle = random.choice(tweet_angles)

    prompt = f"""Write a Twitter/X post about {angle}.

Rules:
- Under 240 characters (leaving room for hashtags)
- Conversational, not corporate
- Start with a hook (number, question, or bold claim)
- Include 3-4 relevant hashtags at the end
- Do NOT include a URL (I'll add that separately)
Output ONLY the tweet text, nothing else."""

    try:
        msg = client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}],
        )
        tweet = msg.choices[0].message.content.strip()
        if product_url and len(tweet) + len(cta) < 280:
            tweet += cta
        return tweet[:280]
    except Exception as e:
        log.warning(f"Groq tweet生成失敗: {e}")
        return f"AI tip for {niche}: Automate repetitive tasks with ChatGPT prompts. #AI #Productivity"


def post_tweet(tweet_text: str) -> bool:
    """Playwright経由でTwitter/Xに投稿。"""
    if not SESSION_FILE.exists():
        log.error("Twitterセッションなし。python twitter.py --setup を実行してください")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(SESSION_FILE))
        page    = context.new_page()
        try:
            page.goto("https://x.com/home", wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            if "login" in page.url or "signin" in page.url:
                log.error("Twitterセッション切れ。python twitter.py --setup を再実行してください")
                return False

            # ツイート入力欄
            for sel in [
                "[data-testid='tweetTextarea_0']",
                "[aria-label='Post text']",
                "[placeholder*='happening']",
            ]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.click()
                    page.wait_for_timeout(500)
                    loc.fill(tweet_text)
                    break

            page.wait_for_timeout(1000)

            # 投稿ボタン
            for sel in ["[data-testid='tweetButtonInline']", "button:has-text('Post')", "[data-testid='tweetButton']"]:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_enabled():
                    loc.click()
                    break

            page.wait_for_timeout(3000)
            context.storage_state(path=str(SESSION_FILE))

            # ログ保存
            POST_LOG.parent.mkdir(parents=True, exist_ok=True)
            log_data = []
            if POST_LOG.exists():
                try:
                    log_data = json.loads(POST_LOG.read_text(encoding="utf-8"))
                except Exception:
                    pass
            log_data.append({"text": tweet_text, "posted_at": datetime.now(timezone.utc).isoformat()})
            POST_LOG.write_text(json.dumps(log_data[-100:], ensure_ascii=False, indent=2), encoding="utf-8")

            log.info(f"Twitter投稿完了: {tweet_text[:50]}...")
            return True

        except Exception as e:
            log.error(f"Twitter投稿エラー: {e}")
            return False
        finally:
            browser.close()


def run_daily(num_posts: int = 3):
    """直近のnicheから複数ツイートを投稿。"""
    niches   = _load_active_niches()
    products = _load_products()

    # 商品URLマップ (niche→URL) 近似マッチ
    product_url_map = {}
    for p in products:
        name = p.get("name", "").lower()
        url  = p.get("short_url", "")
        for niche in niches:
            if any(w in name for w in niche.lower().split()):
                product_url_map[niche] = url

    success = 0
    for i in range(num_posts):
        niche = niches[i % len(niches)]
        url   = product_url_map.get(niche, "")

        # 3投稿のうち1つだけURLを含める
        include_url = (i == num_posts - 1) and url
        tweet = generate_tip_tweet(niche, product_url=url if include_url else "")

        if post_tweet(tweet):
            success += 1
            import time; time.sleep(60)  # 1分間隔で投稿

    log.info(f"Twitter日次投稿完了: {success}/{num_posts}")
    return success


def setup_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page    = context.new_page()
        page.goto("https://x.com/login")
        print("\nブラウザでTwitter/Xにログインしてください。")
        print("ホーム画面が表示されたら Enter を押してください。")
        input(">>> Enter: ")
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_FILE))
        print("Twitterセッション保存完了。")
        browser.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="[twitter] %(asctime)s %(message)s")
    if "--setup" in sys.argv:
        setup_session()
    else:
        n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
        run_daily(num_posts=n)
