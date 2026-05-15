"""
AI News Daily Digest — HackerNews & ProductHunt からAI関連ニュースを自動収集
→ Geminiで要約・英語コンテンツ生成 → Dev.to + GitHub Pages に投稿
毎日JST 9:00実行（朝のニュース感）
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_ROOT       = Path(__file__).parent.parent.parent.parent.parent
STATE_FILE  = Path(__file__).parent / "state.json"
BLOG_EN_DIR = _ROOT / "docs" / "blog" / "en"
SITE_URL    = "https://ryuu321.github.io/ai-holdings"

GEMINI_KEY  = os.environ.get("GEMINI_API_KEY", "")
DEVTO_KEY   = os.environ.get("DEVTO_API_KEY", "")

# AI/Tech関連キーワード（スコア30以上 + これらのワードを含む記事のみ）
AI_KEYWORDS = [
    "AI", "LLM", "GPT", "Claude", "Gemini", "OpenAI", "Anthropic", "machine learning",
    "neural", "ChatGPT", "artificial intelligence", "automation", "productivity",
    "startup", "SaaS", "indie hacker", "side hustle", "passive income", "remote work",
    "career", "freelance", "prompt", "agent", "RAG", "fine-tun",
]


# ─── HackerNews データ取得 ────────────────────────────────────────────

def _fetch_hn_stories(limit: int = 30) -> list[dict]:
    """HN Top Storiesからスコア高めのAI関連記事を取得。"""
    try:
        req = urllib.request.Request(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            ids = json.loads(r.read())[:100]
    except Exception as e:
        print(f"  [HN SKIP] {e}")
        return []

    stories = []
    for sid in ids:
        try:
            req2 = urllib.request.Request(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
            with urllib.request.urlopen(req2, timeout=6) as r:
                s = json.loads(r.read())
            if not s or s.get("type") != "story":
                continue
            title = s.get("title", "")
            score = s.get("score", 0)
            if score < 30:
                continue
            if not any(kw.lower() in title.lower() for kw in AI_KEYWORDS):
                continue
            stories.append({
                "title": title,
                "url": s.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                "score": score,
                "comments": s.get("descendants", 0),
                "hn_id": sid,
            })
            if len(stories) >= limit:
                break
        except Exception:
            continue
    return sorted(stories, key=lambda x: x["score"], reverse=True)[:10]


# ─── Gemini でダイジェスト記事生成 ─────────────────────────────────────

def _generate_digest(stories: list[dict], date_str: str) -> dict | None:
    if not GEMINI_KEY or not stories:
        return None

    try:
        from google import genai
    except ImportError:
        print("  [SKIP] google-genai not installed")
        return None

    client = genai.Client(api_key=GEMINI_KEY)
    stories_text = "\n".join(
        f"{i+1}. [{s['score']}pts] {s['title']} — {s['url']}"
        for i, s in enumerate(stories)
    )

    prompt = f"""You are a tech journalist writing a daily AI & productivity news digest for a developer/entrepreneur audience.

Today's top AI/tech stories from Hacker News ({date_str}):
{stories_text}

Write a compelling daily digest article. Requirements:
- Title: "Today's AI & Tech Digest: [3-4 key themes] ({date_str})" — plain ASCII only
- Opening: 2-sentence summary of the day's biggest theme
- For each story: 1-2 sentence analysis with the business/career implication (not just what happened — WHY it matters)
- End with: "What This Means for You" section — 3 actionable takeaways for professionals using AI
- Add this exact CTA at the end (verbatim):
  ---
  📊 Get my daily AI investment signals free → https://t.me/+yUiqVJi2uNFiOTA1
  🛠️ Save time with AI prompt packs → https://ryuumg.gumroad.com

- Target length: 600-900 words
- Tone: smart, direct, no hype

Return valid JSON only:
{{
  "title": "...",
  "subtitle": "Your daily briefing on AI, productivity, and tech that matters",
  "body": "...",
  "tags": ["ai", "news", "productivity", "technology", "career"]
}}"""

    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model="gemini-flash-latest",
                contents=prompt,
                config={"temperature": 0.6},
            )
            text = resp.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except Exception as e:
            err = str(e)
            if attempt < 2 and ("429" in err or "503" in err or "RESOURCE_EXHAUSTED" in err):
                time.sleep(60 * (attempt + 1))
            else:
                print(f"  [Gemini ERROR] {e}")
                return None
    return None


# ─── Dev.to 投稿 ──────────────────────────────────────────────────────

def _publish_devto(title: str, subtitle: str, body: str, tags: list,
                   canonical_url: str) -> str:
    if not DEVTO_KEY:
        return ""
    full_body = f"*{subtitle}*\n\n{body}" if subtitle else body
    clean_tags = [t.lower().replace(" ", "")[:20] for t in tags[:4] if t.strip()]
    payload_dict: dict = {
        "title": title,
        "body_markdown": full_body,
        "published": True,
        "tags": clean_tags,
    }
    if canonical_url:
        payload_dict["canonical_url"] = canonical_url
    payload = json.dumps({"article": payload_dict}).encode("utf-8")
    req = urllib.request.Request(
        "https://dev.to/api/articles",
        data=payload,
        headers={"api-key": DEVTO_KEY, "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get("url", "")


# ─── GitHub Pages HTML 保存 ───────────────────────────────────────────

_PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | AI Holdings</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta name="robots" content="index, follow">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a2e;background:#f8f9ff;line-height:1.7}}
.hero{{background:linear-gradient(135deg,#0f3460,#16213e);color:#fff;padding:40px 20px;text-align:center}}
.hero h1{{font-size:1.8em;line-height:1.3}}
.container{{max-width:820px;margin:0 auto;padding:32px 20px}}
.body-text h2{{font-size:1.3em;color:#0f3460;margin:20px 0 8px;border-left:3px solid #f5a623;padding-left:10px}}
.body-text p{{margin:10px 0}}
.body-text ul,.body-text ol{{padding-left:20px;margin:8px 0}}
.body-text li{{margin:4px 0}}
.body-text a{{color:#0f3460}}
.body-text strong{{font-weight:700}}
footer{{text-align:center;padding:24px;color:#666;font-size:.85em}}
</style>
</head>
<body>
<div class="hero"><h1>{title}</h1><p style="opacity:.8;margin-top:8px">{date}</p></div>
<div class="container"><div class="body-text">
"""


def _md_to_html(md: str) -> str:
    h = re.sub(r"^## (.+)$", r"<h2>\1</h2>", md, flags=re.MULTILINE)
    h = re.sub(r"^### (.+)$", r"<h3>\1</h3>", h, flags=re.MULTILINE)
    h = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", h)
    h = re.sub(r"\*(.+?)\*", r"<em>\1</em>", h)
    h = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', h)
    h = re.sub(r"\n\n+", "</p><p>", h)
    return f"<p>{h}</p>"


def _save_html(article: dict, slug: str, canonical_url: str, date_str: str):
    BLOG_EN_DIR.mkdir(parents=True, exist_ok=True)
    title = article.get("title", "")
    subtitle = article.get("subtitle", "")
    body_md = article.get("body", "")
    desc = subtitle or body_md[:120].replace("\n", " ").strip() + "..."
    html = _PAGE_HEAD.format(title=title, desc=desc, canonical=canonical_url, date=date_str)
    if subtitle:
        html += f"<p><em>{subtitle}</em></p>\n"
    html += _md_to_html(body_md)
    html += f"""</div></div>
<footer><p>© 2026 AI Holdings | <a href="{SITE_URL}">Home</a></p></footer>
</body></html>"""
    (BLOG_EN_DIR / f"{slug}.html").write_text(html, encoding="utf-8")


# ─── 状態管理 ────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"published_dates": [], "total": 0}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ─── メイン ───────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*50}")
    print("[news_publisher] AI News Digest 開始")

    state = _load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if today in state.get("published_dates", []):
        print(f"  [SKIP] 本日({today})は既に投稿済み")
        return

    # Step1: HNからAIニュース収集
    print("  HackerNewsから記事収集中...")
    stories = _fetch_hn_stories()
    print(f"  {len(stories)}件のAI関連記事を取得")
    if len(stories) < 3:
        print("  [SKIP] 記事が少なすぎる")
        return

    # Step2: Geminiでダイジェスト生成
    print("  Geminiでダイジェスト生成中...")
    article = _generate_digest(stories, today)
    if not article:
        print("  [SKIP] ダイジェスト生成失敗")
        return
    print(f"  英題: {article.get('title', '')[:60]}")

    # Step3: GitHub Pages保存 → canonical_url確立
    title = article.get("title", "")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:60].strip("-")
    canonical_url = f"{SITE_URL}/blog/en/{slug}.html"
    try:
        _save_html(article, slug, canonical_url, today)
        print(f"  GitHub Pages保存: blog/en/{slug}.html")
    except Exception as e:
        print(f"  [HTML SKIP] {e}")
        canonical_url = ""

    # Step4: Dev.to投稿
    try:
        url = _publish_devto(
            article.get("title", ""),
            article.get("subtitle", ""),
            article.get("body", ""),
            article.get("tags", ["ai", "news", "productivity"]),
            canonical_url,
        )
        print(f"  Dev.to投稿完了: {url}")
        state.setdefault("published_dates", []).append(today)
        state["total"] = state.get("total", 0) + 1
        _save_state(state)
    except Exception as e:
        print(f"  [Dev.to ERROR] {e}")

    print(f"[完了] 通算{state.get('total', 0)}件")


if __name__ == "__main__":
    main()
