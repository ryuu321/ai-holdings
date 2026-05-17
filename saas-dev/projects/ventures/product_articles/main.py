"""
product_articles/main.py
毎週実行: 各Gumroad商品に対応したバイヤーインテント記事を生成 → Dev.to + GitHub Pages投稿
ターゲット: "ChatGPT prompts for [niche]" 系の購買意欲の高いキーワード
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_ROOT       = Path(__file__).parent.parent.parent.parent.parent
STATE_FILE  = Path(__file__).parent / "state.json"
BLOG_EN_DIR = _ROOT / "docs" / "blog" / "en"
SITE_URL    = "https://ryuu321.github.io/ai-holdings"

GEMINI_KEY  = os.environ.get("GEMINI_API_KEY", "")
DEVTO_KEY   = os.environ.get("DEVTO_API_KEY", "")
MEDIUM_KEY  = os.environ.get("MEDIUM_INTEGRATION_TOKEN", "")
TG_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_CHANNEL  = os.environ.get("TELEGRAM_CHANNEL_ID", "")


# 6商品 × 複数記事トピック（週次ローテーション）
PRODUCT_TOPICS = [
    {
        "product": "ADHD Unlocked",
        "url": "https://ryuumg.gumroad.com/l/akikab",
        "devto_tags": ["adhd", "productivity", "ai", "mentalhealth"],
        "articles": [
            {
                "keyword": "ChatGPT prompts for ADHD productivity",
                "angle": "personal story: how I use ChatGPT to manage ADHD task paralysis",
                "prompt_theme": "task breakdown, priority setting, routine building, focus sessions",
                "title_hint": "The 7 ChatGPT Prompts I Use Every Day to Manage ADHD (That Actually Work)",
            },
            {
                "keyword": "AI tools for ADHD adults",
                "angle": "practical guide: building an ADHD-friendly workflow with AI",
                "prompt_theme": "time blindness, working memory, emotional regulation, transitions",
                "title_hint": "I Have ADHD and I Built a System With AI That Finally Stuck",
            },
        ],
    },
    {
        "product": "AI Content Boost",
        "url": "https://ryuumg.gumroad.com/l/qhanl",
        "devto_tags": ["contentcreation", "ai", "productivity", "socialmedia"],
        "articles": [
            {
                "keyword": "ChatGPT prompts for content creators",
                "angle": "practical guide: batch a week of content in 2 hours using AI",
                "prompt_theme": "hooks, content calendars, repurposing, caption writing",
                "title_hint": "How I Batch 30 Days of Content in 2 Hours Using ChatGPT",
            },
            {
                "keyword": "AI for social media content",
                "angle": "breakdown: the exact AI workflow that doubled my engagement",
                "prompt_theme": "viral hooks, story frameworks, engagement questions, CTAs",
                "title_hint": "The AI Prompts Behind My Most Viral Posts (Copy Them)",
            },
        ],
    },
    {
        "product": "Etsy Seller Boost",
        "url": "https://ryuumg.gumroad.com/l/nnijeb",
        "devto_tags": ["etsy", "ecommerce", "ai", "smallbusiness"],
        "articles": [
            {
                "keyword": "ChatGPT for Etsy sellers",
                "angle": "personal story: I rewrote all my Etsy listings with AI — here's the result",
                "prompt_theme": "SEO titles, product descriptions, tags, customer messages",
                "title_hint": "I Used ChatGPT to Rewrite 40 Etsy Listings — Sales Jumped 34%",
            },
            {
                "keyword": "AI prompts for Etsy SEO",
                "angle": "tutorial: how to write Etsy listings that rank using AI",
                "prompt_theme": "keyword research, title optimization, description structure",
                "title_hint": "The AI Prompt Formula for Etsy Listings That Actually Get Found",
            },
        ],
    },
    {
        "product": "DesignGenie",
        "url": "https://ryuumg.gumroad.com/l/zkiwh",
        "devto_tags": ["design", "ai", "freelance", "graphicdesign"],
        "articles": [
            {
                "keyword": "ChatGPT prompts for graphic designers",
                "angle": "workflow breakdown: how I use AI before opening Illustrator",
                "prompt_theme": "creative briefs, client communication, concept naming, portfolio copy",
                "title_hint": "The AI Workflow I Do Before I Open Illustrator (5 Prompts)",
            },
            {
                "keyword": "AI tools for freelance designers",
                "angle": "practical guide: using AI to win more clients and charge more",
                "prompt_theme": "proposals, pricing, client onboarding, case study writing",
                "title_hint": "How I Use AI to Write Proposals That Win Design Clients",
            },
        ],
    },
    {
        "product": "Viral Content",
        "url": "https://ryuumg.gumroad.com/l/rboqqr",
        "devto_tags": ["viral", "contentmarketing", "ai", "writing"],
        "articles": [
            {
                "keyword": "ChatGPT viral content prompts",
                "angle": "analysis: I reverse-engineered 50 viral posts — here are the patterns",
                "prompt_theme": "hook formulas, emotional triggers, story arcs, pattern interrupts",
                "title_hint": "I Analyzed 50 Viral Posts and Built These AI Prompts From the Patterns",
            },
            {
                "keyword": "AI prompts for viral hooks",
                "angle": "breakdown: the 5 hook types that get shares every time",
                "prompt_theme": "curiosity gaps, contrarian takes, relatable pain, bold claims",
                "title_hint": "5 Hook Formulas That Make Any Post More Shareable (With AI Prompts)",
            },
        ],
    },
    {
        "product": "Procreate AI",
        "url": "https://ryuumg.gumroad.com/l/yugogd",
        "devto_tags": ["procreate", "art", "ai", "illustration"],
        "articles": [
            {
                "keyword": "ChatGPT prompts for Procreate artists",
                "angle": "practical guide: using AI as a creative director for your art",
                "prompt_theme": "composition ideas, color palettes, style development, art series planning",
                "title_hint": "How I Use ChatGPT as My Art Director for Procreate (With Real Prompts)",
            },
            {
                "keyword": "AI for digital artists",
                "angle": "story: how AI helped me develop a consistent art style",
                "prompt_theme": "style analysis, artistic influences, composition feedback, series planning",
                "title_hint": "I Used AI to Define My Art Style — Here's How (And the Prompts I Used)",
            },
        ],
    },
    {
        "product": "AI Content Boost",
        "url": "https://ryuumg.gumroad.com/l/qhanl",
        "devto_tags": ["freelance", "ai", "productivity", "business"],
        "articles": [
            {
                "keyword": "ChatGPT prompts for freelancers",
                "angle": "personal story: how I use AI to win better clients and stop undercharging",
                "prompt_theme": "proposals, pricing, scope creep, cold outreach, client communication",
                "title_hint": "The ChatGPT Prompts That Helped Me Raise My Freelance Rate by 40%",
            },
            {
                "keyword": "AI tools for freelance business",
                "angle": "practical guide: 5 places in my freelance workflow where AI saves 5+ hours a week",
                "prompt_theme": "contracts, client onboarding, invoicing follow-up, project scope, case studies",
                "title_hint": "5 Parts of My Freelance Business I Handed to AI (And Never Looked Back)",
            },
        ],
    },
    {
        "product": "Viral Content",
        "url": "https://ryuumg.gumroad.com/l/rboqqr",
        "devto_tags": ["writing", "ai", "blogging", "contentcreation"],
        "articles": [
            {
                "keyword": "ChatGPT prompts for writers",
                "angle": "practical guide: using AI to beat writer's block and write 3x faster",
                "prompt_theme": "outlining, voice development, scene writing, editing, overcoming blocks",
                "title_hint": "How I Use ChatGPT to Write 3x Faster Without Losing My Voice",
            },
            {
                "keyword": "AI prompts for social media managers",
                "angle": "workflow breakdown: how I manage 8 client accounts using AI",
                "prompt_theme": "content calendars, brand voice, reporting, client communication, crisis response",
                "title_hint": "How I Manage 8 Social Media Accounts Without Burning Out (AI Workflow)",
            },
        ],
    },
    {
        "product": "AI Content Boost",
        "url": "https://ryuumg.gumroad.com/l/qhanl",
        "devto_tags": ["virtualassistant", "ai", "productivity", "freelance"],
        "articles": [
            {
                "keyword": "ChatGPT prompts for virtual assistants",
                "angle": "practical guide: using AI to handle 3x more client work without working more hours",
                "prompt_theme": "client onboarding, inbox management, meeting notes, weekly updates, scope management",
                "title_hint": "The AI Prompts I Use to Manage 5 Clients Without Working More Than 40 Hours",
            },
            {
                "keyword": "AI tools for VA business",
                "angle": "breakdown: how AI helps me offer more services and charge higher rates",
                "prompt_theme": "research reports, client communication, rate increases, service packaging, client retention",
                "title_hint": "How I Used AI to Raise My VA Rate From $20 to $45/Hour (With the Prompts)",
            },
        ],
    },
    {
        "product": "AI Content Boost",
        "url": "https://ryuumg.gumroad.com/l/qhanl",
        "devto_tags": ["fitness", "coaching", "ai", "business"],
        "articles": [
            {
                "keyword": "ChatGPT prompts for fitness coaches",
                "angle": "practical guide: using AI to design programs and retain clients without burning out",
                "prompt_theme": "program templates, progressive overload, nutrition frameworks, check-in systems, client communication",
                "title_hint": "How I Use ChatGPT to Build Client Programs in 20 Minutes (Instead of 2 Hours)",
            },
            {
                "keyword": "AI for fitness coaching business",
                "angle": "story: how I used AI to go from 8 to 20 clients without hiring staff",
                "prompt_theme": "social media content, discovery calls, onboarding, testimonials, educational content",
                "title_hint": "I Doubled My Fitness Coaching Clients Using AI — Here's Exactly How",
            },
        ],
    },
    {
        "product": "DesignGenie",
        "url": "https://ryuumg.gumroad.com/l/zkiwh",
        "devto_tags": ["photography", "smallbusiness", "ai", "creative"],
        "articles": [
            {
                "keyword": "ChatGPT prompts for photographers",
                "angle": "practical guide: using AI to handle the business side so you can focus on shooting",
                "prompt_theme": "client inquiry responses, gallery delivery, pricing guides, upsell sequences, venue pitches",
                "title_hint": "The ChatGPT Prompts That Handle My Photography Business Admin (So I Can Just Shoot)",
            },
            {
                "keyword": "AI for photography business",
                "angle": "breakdown: 5 places in my photography workflow where AI saves me 10+ hours a week",
                "prompt_theme": "inquiry templates, booking confirmations, contract emails, social captions, referral asks",
                "title_hint": "5 Photography Business Tasks I Handed to AI — And Never Looked Back",
            },
        ],
    },
    {
        "product": "AI Content Boost",
        "url": "https://ryuumg.gumroad.com/l/qhanl",
        "devto_tags": ["hr", "recruiting", "ai", "management"],
        "articles": [
            {
                "keyword": "ChatGPT prompts for HR professionals",
                "angle": "practical guide: using AI to write better job postings, handle difficult conversations, and save 5+ hours a week",
                "prompt_theme": "job postings, interview questions, performance reviews, difficult conversations, policy rewrites",
                "title_hint": "The ChatGPT Prompts That Make Hard HR Conversations Easier (And Faster)",
            },
            {
                "keyword": "AI prompts for recruiters",
                "angle": "workflow breakdown: how I use AI to screen faster and write job postings that attract better candidates",
                "prompt_theme": "inclusive job postings, structured interview questions, offer communication, candidate nurturing",
                "title_hint": "How I Use AI to Write Job Postings That Attract 3x More Qualified Applicants",
            },
        ],
    },
]


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"published": [], "total": 0, "product_index": 0}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _pick_topic(state: dict) -> tuple[dict, dict] | None:
    published = set(state.get("published", []))
    idx = state.get("product_index", 0)
    for _ in range(len(PRODUCT_TOPICS) * 3):
        product = PRODUCT_TOPICS[idx % len(PRODUCT_TOPICS)]
        for article in product["articles"]:
            key = f"{product['product']}::{article['keyword']}"
            if key not in published:
                state["product_index"] = idx
                return product, article
        idx += 1
    return None


def _generate_article(product: dict, topic: dict, date_str: str) -> dict | None:
    if not GEMINI_KEY:
        return None
    try:
        from google import genai
    except ImportError:
        print("  [SKIP] google-genai not installed")
        return None

    client = genai.Client(api_key=GEMINI_KEY)
    prompt = f"""You are a blogger writing for developers and digital entrepreneurs on Dev.to.

Write a first-person, practical article about: "{topic['keyword']}"

Article angle: {topic['angle']}
Key prompt themes to include: {topic['prompt_theme']}
Suggested title direction: {topic['title_hint']}
Today's date: {date_str}

Requirements:
- Title: compelling, specific, SEO-optimized for "{topic['keyword']}" — plain ASCII only, no special characters
- Write in first person ("I use this every week", "When I tried this...")
- Include 5-7 specific, copy-pasteable AI prompts embedded in the article
- Format prompts inside code blocks (``` ```)
- Each prompt should have a sentence of context explaining when/why to use it
- Length: 700-1000 words
- Tone: direct, practical, no fluff — like advice from a friend who's figured this out
- End with: "Want 50 more [niche] AI prompts? [Product name] has the full library — get it on Gumroad: {product['url']}"
- Do NOT use markdown headers before the first paragraph — jump right into the content
- Include "## " headers for major sections (not for the title)

Return valid JSON only (no markdown fences):
{{
  "title": "...",
  "subtitle": "Practical AI prompts for {product['product'].split()[0]} practitioners — tested and ready to copy",
  "body": "...",
  "tags": {json.dumps(product['devto_tags'])}
}}"""

    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model="gemini-flash-latest",
                contents=prompt,
                config={"temperature": 0.7},
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


def _save_html(article: dict, slug: str, canonical_url: str, date_str: str):
    BLOG_EN_DIR.mkdir(parents=True, exist_ok=True)
    title = article.get("title", "")
    subtitle = article.get("subtitle", "")
    body_md = article.get("body", "")
    desc = subtitle[:160] if subtitle else body_md[:160].replace("\n", " ") + "..."

    def md_to_html(md: str) -> str:
        h = re.sub(r"^## (.+)$", r"<h2>\1</h2>", md, flags=re.MULTILINE)
        h = re.sub(r"^### (.+)$", r"<h3>\1</h3>", h, flags=re.MULTILINE)
        h = re.sub(r"```([^`]*)```", r"<pre><code>\1</code></pre>", h, flags=re.DOTALL)
        h = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", h)
        h = re.sub(r"\*(.+?)\*", r"<em>\1</em>", h)
        h = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', h)
        paragraphs = re.split(r"\n\n+", h)
        result = []
        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            if p.startswith("<h") or p.startswith("<pre") or p.startswith("<ul") or p.startswith("<ol"):
                result.append(p)
            else:
                result.append(f"<p>{p}</p>")
        return "\n".join(result)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | AI Holdings</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical_url}">
<meta name="robots" content="index, follow">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a2e;background:#f8f9ff;line-height:1.7}}
.hero{{background:linear-gradient(135deg,#0f3460,#16213e);color:#fff;padding:40px 20px;text-align:center}}
.hero h1{{font-size:1.8em;line-height:1.3;max-width:800px;margin:0 auto}}
.container{{max-width:820px;margin:0 auto;padding:32px 20px}}
.body-text h2{{font-size:1.3em;color:#0f3460;margin:24px 0 10px;border-left:3px solid #f5a623;padding-left:10px}}
.body-text h3{{font-size:1.1em;color:#16213e;margin:18px 0 8px}}
.body-text p{{margin:10px 0}}
.body-text pre{{background:#f0f4ff;border:1px solid #c5d0f0;border-radius:6px;padding:14px;margin:12px 0;overflow-x:auto;font-size:.88em;line-height:1.5}}
.body-text code{{font-family:'Courier New',monospace}}
.body-text a{{color:#0f3460}}
.body-text strong{{font-weight:700}}
footer{{text-align:center;padding:24px;color:#666;font-size:.85em}}
</style>
</head>
<body>
<div class="hero"><h1>{title}</h1><p style="opacity:.8;margin-top:8px">{date_str}</p></div>
<div class="container"><div class="body-text">
{md_to_html(body_md)}
</div></div>
<footer><p>© 2026 AI Holdings | <a href="{SITE_URL}">Home</a> | <a href="{SITE_URL}/blog/guides/">Free Guides</a></p></footer>
</body></html>"""
    (BLOG_EN_DIR / f"{slug}.html").write_text(html, encoding="utf-8")


def _publish_devto(title: str, subtitle: str, body: str, tags: list, canonical_url: str) -> str:
    if not DEVTO_KEY:
        return ""
    full_body = f"*{subtitle}*\n\n{body}" if subtitle else body
    clean_tags = [t.lower().replace(" ", "")[:20] for t in tags[:4] if t.strip()]
    payload_dict = {
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


def _publish_medium(title: str, body: str, tags: list, canonical_url: str) -> str:
    """Medium Integration Token を使って投稿。canonicalUrlで重複コンテンツを防ぐ。"""
    if not MEDIUM_KEY:
        return ""
    try:
        # ユーザーID取得
        req = urllib.request.Request(
            "https://api.medium.com/v1/me",
            headers={"Authorization": f"Bearer {MEDIUM_KEY}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            user_id = json.loads(r.read()).get("data", {}).get("id", "")
        if not user_id:
            return ""

        payload = json.dumps({
            "title": title,
            "contentFormat": "markdown",
            "content": body,
            "canonicalUrl": canonical_url,
            "publishStatus": "public",
            "tags": [t[:25] for t in tags[:5]],
        }).encode("utf-8")
        req2 = urllib.request.Request(
            f"https://api.medium.com/v1/users/{user_id}/posts",
            data=payload,
            headers={"Authorization": f"Bearer {MEDIUM_KEY}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req2, timeout=30) as r:
            url = json.loads(r.read()).get("data", {}).get("url", "")
        print(f"  Medium投稿完了: {url}")
        return url
    except Exception as e:
        print(f"  [Medium SKIP] {e}")
        return ""


def _send_telegram(title: str, devto_url: str, product_url: str, product_name: str):
    if not TG_TOKEN or not TG_CHANNEL:
        return
    link = devto_url or product_url
    msg = (
        f"📝 <b>New Article</b>\n\n"
        f"<b>{title}</b>\n\n"
        f"<a href='{link}'>Read on Dev.to →</a>\n\n"
        f"📦 Full prompt pack: <a href='{product_url}'>{product_name} on Gumroad</a>"
    )
    data = json.dumps({
        "chat_id": TG_CHANNEL,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
        if result.get("ok"):
            print("  Telegram配信完了")
    except Exception as e:
        print(f"  [Telegram SKIP] {e}")


def main():
    print(f"\n{'='*50}")
    print("[product_articles] バイヤーインテント記事配信 開始")

    state = _load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 週次実行（1日1記事まで）
    if today in state.get("published_dates_daily", []):
        print(f"  [SKIP] 本日({today})は既に投稿済み")
        return

    result = _pick_topic(state)
    if not result:
        print("  [SKIP] 全トピック配信済み（リセット）")
        state["published"] = []
        state["product_index"] = 0
        _save_state(state)
        return

    product, topic = result
    print(f"  商品: {product['product']}")
    print(f"  キーワード: {topic['keyword']}")

    # Step1: Gemini記事生成
    print("  Gemini記事生成中...")
    article = _generate_article(product, topic, today)
    if not article:
        print("  [SKIP] 生成失敗")
        return
    print(f"  タイトル: {article.get('title', '')[:70]}")

    # Step2: GitHub Pages保存
    title = article.get("title", "")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:60].strip("-")
    canonical_url = f"{SITE_URL}/blog/en/{slug}.html"
    try:
        _save_html(article, slug, canonical_url, today)
        print(f"  GitHub Pages保存: blog/en/{slug}.html")
    except Exception as e:
        print(f"  [HTML SKIP] {e}")
        canonical_url = ""

    # Step3: Dev.to投稿
    devto_url = ""
    try:
        devto_url = _publish_devto(
            article.get("title", ""),
            article.get("subtitle", ""),
            article.get("body", ""),
            article.get("tags", []),
            canonical_url,
        )
        print(f"  Dev.to投稿完了: {devto_url}")
    except Exception as e:
        print(f"  [Dev.to ERROR] {e}")

    # Step3b: Medium投稿（canonicalはGitHub Pages）
    _publish_medium(
        article.get("title", ""),
        article.get("body", ""),
        article.get("tags", []),
        canonical_url,
    )

    # Step4: 状態更新
    key = f"{product['product']}::{topic['keyword']}"
    state.setdefault("published", []).append(key)
    state.setdefault("published_dates_daily", []).append(today)
    state["total"] = state.get("total", 0) + 1
    state["product_index"] = (state.get("product_index", 0) + 1) % len(PRODUCT_TOPICS)
    _save_state(state)

    # Step5: Telegram配信
    _send_telegram(title, devto_url, product["url"], product["product"])

    print(f"[完了] 通算{state['total']}記事配信")


if __name__ == "__main__":
    main()
