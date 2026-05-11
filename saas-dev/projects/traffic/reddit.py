"""Reddit 有益コメント自動投稿 — 関連スレに価値提供してGumroad誘導"""
import os
import json
import logging
import random
import time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq
import requests
from playwright.sync_api import sync_playwright

_ROOT = Path(__file__).parent.parent.parent.parent
load_dotenv(_ROOT / ".env")

GROQ_KEY     = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL   = "llama-3.3-70b-versatile"
SESSION_FILE = Path(__file__).parent / "data" / "reddit_session.json"
POST_LOG     = Path(__file__).parent / "data" / "reddit_posted.json"

GUMROAD_STRATEGY = Path(__file__).parent.parent / "gumroad" / "data" / "strategy.json"

# ニッチ → 関連サブレdit
NICHE_SUBREDDITS = {
    "Content Creators":     ["r/NewTubers", "r/ContentCreation", "r/blogging"],
    "ADHD Productivity":    ["r/ADHD", "r/productivity", "r/adhdmeme"],
    "Solopreneurs":         ["r/Entrepreneur", "r/SideProject", "r/smallbusiness"],
    "UX Designers":         ["r/UXDesign", "r/userexperience"],
    "Virtual Assistants":   ["r/VirtualAssistant", "r/WorkOnline"],
    "Etsy Sellers":         ["r/EtsySellers", "r/Etsy"],
    "Fitness Coaches":      ["r/personaltraining", "r/fitness"],
    "Podcast Creators":     ["r/podcasting"],
    "Graphic Designers":    ["r/graphic_design", "r/design"],
    "Remote Team Managers": ["r/remotework", "r/managers"],
    "Life Coaches":         ["r/lifecoaching", "r/selfimprovement"],
    "SaaS Founders":        ["r/SaaS", "r/startups"],
    "E-commerce Entrepreneurs": ["r/ecommerce", "r/dropship"],
    "Real Estate Agents":   ["r/RealEstate", "r/realtors"],
    "Freelance Copywriters":["r/copywriting", "r/freelanceWriters"],
}
# 全ニッチ共通の大きなサブレdit
GENERAL_SUBREDDITS = ["r/ChatGPT", "r/artificial", "r/Notion", "r/productivity"]

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)",
    "Accept": "application/json",
}

log = logging.getLogger(__name__)


# ─────────────────────── 投稿検索 ───────────────────────

def _load_posted() -> set:
    if POST_LOG.exists():
        try:
            data = json.loads(POST_LOG.read_text(encoding="utf-8"))
            return set(data.get("post_ids", []))
        except Exception:
            pass
    return set()


def _save_posted(post_id: str, comment: str):
    posted = _load_posted()
    posted.add(post_id)
    POST_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_data = {"post_ids": list(posted)[-200:]}
    if POST_LOG.exists():
        try:
            log_data = json.loads(POST_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    log_data["post_ids"] = list(posted)[-200:]
    log_data.setdefault("history", []).append({
        "post_id": post_id,
        "comment": comment[:100],
        "posted_at": datetime.now(timezone.utc).isoformat(),
    })
    log_data["history"] = log_data["history"][-50:]
    POST_LOG.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")


def find_relevant_posts(subreddit: str, limit: int = 10) -> list[dict]:
    """subredditのhotスレからコメントできそうな投稿を取得。"""
    sub = subreddit.lstrip("r/")
    posted_ids = _load_posted()
    results = []
    try:
        r = requests.get(
            f"https://www.reddit.com/{subreddit}/hot.json?limit={limit}",
            headers=SCRAPE_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        posts = r.json().get("data", {}).get("children", [])
        for p in posts:
            d = p.get("data", {})
            pid = d.get("id", "")
            # 除外: 既投稿済み、固定、リンクのみ、コメント数が多すぎ（埋もれる）
            if (pid in posted_ids or d.get("stickied") or
                    d.get("is_self") is False or d.get("num_comments", 0) > 200):
                continue
            title = d.get("title", "")
            body  = d.get("selftext", "")[:500]
            if len(title) < 10:
                continue
            results.append({
                "id":       pid,
                "subreddit": sub,
                "title":    title,
                "body":     body,
                "url":      f"https://www.reddit.com{d.get('permalink','')}",
                "comments": d.get("num_comments", 0),
            })
    except Exception as e:
        log.warning(f"Reddit {subreddit} 取得失敗: {e}")
    return results


def generate_helpful_comment(post_title: str, post_body: str, niche: str, product_url: str = "") -> str:
    """Groqで投稿に対する有益なコメントを生成。リンクは含めない。"""
    if not GROQ_KEY:
        return ""

    # 5投稿に1回だけ製品への言及を入れる
    mention_product = bool(product_url) and random.random() < 0.2
    product_note = (
        f"\n\nAt the end, naturally mention that you put together a free resource / full guide "
        f"on this topic (don't include a URL, just say 'feel free to DM me')."
        if mention_product else ""
    )

    prompt = f"""You're a helpful Reddit user who is an expert in productivity and AI tools.
Someone posted in r/{niche.replace(' ', '')} with this post:

Title: {post_title}
Body: {post_body or '(no body)'}

Write a genuinely helpful, specific comment that:
- Directly addresses their question or situation
- Shares 2-3 practical tips they can use immediately
- Sounds like a real person, not a bot (conversational tone)
- Is 100-200 words
- Does NOT mention any product or URL
- Does NOT start with "Great post!" or similar
{product_note}

Output ONLY the comment text."""

    try:
        msg = Groq(api_key=GROQ_KEY).chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.choices[0].message.content.strip()
    except Exception as e:
        log.warning(f"Groqコメント生成失敗: {e}")
        return ""


# ─────────────────────── Playwright投稿 ───────────────────────

def post_comment(post_url: str, comment_text: str) -> bool:
    """Playwright経由でRedditにコメント投稿。"""
    if not SESSION_FILE.exists():
        log.error("Redditセッションなし。python reddit.py --setup を実行してください")
        return False
    if not comment_text.strip():
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(SESSION_FILE))
        page    = context.new_page()
        try:
            page.goto(post_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            if "login" in page.url or "register" in page.url:
                log.error("Redditセッション切れ。python reddit.py --setup を再実行してください")
                return False

            # コメント入力欄（new Reddit UI）
            for sel in [
                "[placeholder*='comment']",
                "[data-click-id='text-body'] div[contenteditable]",
                ".public-DraftEditor-content",
                "div[role='textbox']",
            ]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.click()
                    page.wait_for_timeout(500)
                    loc.fill(comment_text)
                    break

            page.wait_for_timeout(1000)

            # 投稿ボタン
            for sel in ["button:has-text('Comment')", "button:has-text('Submit')", "[data-click-id='submit-comment']"]:
                loc = page.locator(sel).last
                if loc.count() > 0 and loc.is_enabled():
                    loc.click()
                    break

            page.wait_for_timeout(4000)
            context.storage_state(path=str(SESSION_FILE))
            log.info(f"Redditコメント投稿完了: {post_url}")
            return True

        except Exception as e:
            log.error(f"Redditコメントエラー: {e}")
            return False
        finally:
            browser.close()


# ─────────────────────── メイン ───────────────────────

def _load_active_niches() -> list[str]:
    defaults = ["Content Creators", "ADHD Productivity", "Solopreneurs"]
    try:
        if GUMROAD_STRATEGY.exists():
            data = json.loads(GUMROAD_STRATEGY.read_text(encoding="utf-8"))
            recent = data.get("used_niches_recent", [])
            if recent:
                return list(dict.fromkeys(reversed(recent)))[:3]
    except Exception:
        pass
    return defaults


def _get_product_url(niche: str) -> str:
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent / "gumroad"))
        from pipeline import GUMROAD_API, GUMROAD_TOKEN
        if not GUMROAD_TOKEN:
            return ""
        r = requests.get(f"{GUMROAD_API}/products",
                         headers={"Authorization": f"Bearer {GUMROAD_TOKEN}"}, timeout=10)
        for p in r.json().get("products", []):
            if p.get("published") and any(
                w in p.get("name", "").lower() for w in niche.lower().split()
            ):
                return p.get("short_url", "")
    except Exception:
        pass
    return ""


def run_daily(max_comments: int = 5):
    """直近のnicheから関連投稿を探してコメント。"""
    niches   = _load_active_niches()
    success  = 0

    # ターゲットサブレditを組み立て
    target_subs = list(GENERAL_SUBREDDITS)
    for niche in niches:
        target_subs += NICHE_SUBREDDITS.get(niche, [])
    random.shuffle(target_subs)

    for sub in target_subs:
        if success >= max_comments:
            break

        niche = next((n for n in niches if any(
            s in sub for s in n.lower().split()
        )), niches[0])

        posts = find_relevant_posts(sub, limit=5)
        if not posts:
            continue

        post = posts[0]  # 最も関連性の高い1件
        product_url = _get_product_url(niche)
        comment = generate_helpful_comment(
            post["title"], post["body"], niche, product_url
        )
        if not comment:
            continue

        log.info(f"コメント試行: {sub} → '{post['title'][:50]}'")
        ok = post_comment(post["url"], comment)
        if ok:
            _save_posted(post["id"], comment)
            success += 1
            time.sleep(120)  # 2分間隔（スパム対策）

    log.info(f"Reddit日次コメント完了: {success}/{max_comments}件")
    return success


def setup_session():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page    = context.new_page()
        page.goto("https://www.reddit.com/login/")
        print("\nブラウザでRedditにログインしてください。")
        print("ホーム画面が表示されたら Enter を押してください。")
        input(">>> Enter: ")
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_FILE))
        print("Redditセッション保存完了。")
        browser.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="[reddit] %(asctime)s %(message)s")
    if "--setup" in sys.argv:
        setup_session()
    else:
        n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
        run_daily(max_comments=n)
