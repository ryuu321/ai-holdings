"""
GitHub Pages 自動ブログ生成
1. Gumroad商品ごとのSEOランディングページ
2. Dev.to記事を静的HTMLで再公開（SEO補強）
3. サイトマップ自動生成 → Google/Bing pingで即インデックス依頼
実行: python generate.py → docs/blog/ に出力
"""
import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_ROOT     = Path(__file__).parent.parent.parent.parent.parent
DOCS_DIR  = _ROOT / "docs"
BLOG_DIR  = DOCS_DIR / "blog"
NOTE_OUT  = _ROOT / "note-biz" / "output"

GUMROAD_TOKEN = os.environ.get("GUMROAD_ACCESS_TOKEN", "")
SITE_URL      = "https://ryuu321.github.io/ai-holdings"


# ─── HTML テンプレート ───────────────────────────────────────────────

PAGE_HEAD = """<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta name="robots" content="index, follow">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a2e;background:#f8f9ff;line-height:1.7}}
.hero{{background:linear-gradient(135deg,#0f3460 0%,#16213e 100%);color:#fff;padding:60px 20px;text-align:center}}
.hero h1{{font-size:2.2em;margin-bottom:12px;line-height:1.3}}
.hero p{{font-size:1.1em;opacity:.85;max-width:600px;margin:0 auto 24px}}
.cta{{display:inline-block;background:#f5a623;color:#000;font-weight:700;padding:14px 32px;border-radius:8px;text-decoration:none;font-size:1.1em;margin-top:8px}}
.cta:hover{{background:#e09010}}
.container{{max-width:820px;margin:0 auto;padding:40px 20px}}
.section{{background:#fff;border-radius:12px;padding:32px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
h2{{font-size:1.5em;color:#0f3460;margin-bottom:16px;border-left:4px solid #f5a623;padding-left:12px}}
ul{{padding-left:20px;margin:12px 0}}
li{{margin:6px 0}}
.price{{font-size:2em;font-weight:700;color:#0f3460;margin:16px 0}}
.badge{{background:#e8f5e9;color:#2e7d32;padding:4px 10px;border-radius:20px;font-size:.85em;font-weight:600}}
.articles{{display:grid;gap:16px;margin-top:16px}}
.article-card{{background:#f8f9ff;border-radius:8px;padding:16px;border-left:3px solid #0f3460}}
.article-card a{{color:#0f3460;font-weight:600;text-decoration:none}}
.article-card a:hover{{text-decoration:underline}}
footer{{text-align:center;padding:32px;color:#666;font-size:.9em}}
</style>
</head>
<body>
"""

PAGE_FOOT = """<footer><p>© 2026 AI Holdings | <a href="{site_url}">Home</a></p></footer>
</body></html>"""


# ─── Gumroad 商品ランディングページ生成 ───────────────────────────────

PRODUCT_SEO = {
    "ADHD Unlocked":     {"kw": "ADHD productivity AI prompts ChatGPT focus system", "desc": "50 ChatGPT prompts to help ADHD professionals stay focused, manage tasks, and boost output. Instant download."},
    "AI Content Boost":  {"kw": "AI content creation prompts ChatGPT blog social media", "desc": "50 AI prompts for content creators to write faster, go viral, and grow audiences."},
    "Viral Content":     {"kw": "viral content prompts ChatGPT social media marketing", "desc": "50 battle-tested prompts for creating viral content across every platform."},
    "Etsy Seller Boost": {"kw": "Etsy seller AI prompts product listing SEO", "desc": "50 ChatGPT prompts to write better Etsy listings, boost SEO, and increase sales."},
    "Etsy Success Boost":{"kw": "Etsy shop growth AI prompts scaling marketing revenue", "desc": "Advanced ChatGPT prompts for scaling your Etsy shop — launch campaigns, email lists, and $5K month strategy."},
    "DesignGenie":       {"kw": "graphic designer AI prompts creative briefs client communication", "desc": "50 AI prompts for graphic designers: creative briefs, client communication, portfolio copy."},
    "Procreate AI":      {"kw": "Procreate AI prompts digital art illustration composition", "desc": "50 AI prompts for Procreate artists — composition ideas, color palettes, style development."},
    "Procreate Aid":     {"kw": "advanced Procreate AI prompts digital art techniques lighting", "desc": "Advanced AI prompts to level up your Procreate artwork — textures, lighting, character design."},
    "Procreate Assets":  {"kw": "Procreate assets sell digital art AI prompts", "desc": "50 AI prompts for Procreate artists who want to create and sell assets, brushes, and client work."},
}


def _fetch_products() -> list[dict]:
    if not GUMROAD_TOKEN:
        return []
    try:
        req = urllib.request.Request(
            "https://api.gumroad.com/v2/products",
            headers={"Authorization": f"Bearer {GUMROAD_TOKEN}"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return [p for p in data.get("products", []) if p.get("published")]
    except Exception as e:
        print(f"  Gumroad取得失敗: {e}")
        return []


def _product_page(p: dict) -> str:
    name  = p.get("name", "")
    price = p.get("price", 3700) / 100
    url   = p.get("short_url", "#")
    seo   = PRODUCT_SEO.get(name, {})
    desc  = seo.get("desc", f"{name} — AI prompt pack for professionals. 50 ready-to-use ChatGPT prompts.")
    kw    = seo.get("kw", f"{name} AI prompts ChatGPT productivity")

    json_ld = f"""<script type="application/ld+json">
{{"@context":"https://schema.org","@type":"Product","name":"{name}","description":"{desc}","offers":{{"@type":"Offer","price":"{price:.2f}","priceCurrency":"USD","availability":"https://schema.org/InStock","url":"{url}"}}}}
</script>"""
    html = PAGE_HEAD.format(lang="en", title=f"{name} | AI Prompt Pack — ${price:.0f}", description=desc)
    html = html.replace("</head>", f"{json_ld}\n</head>")
    html += f"""
<div class="hero">
  <h1>{name}</h1>
  <p>{desc}</p>
  <a class="cta" href="{url}" rel="nofollow" target="_blank">Get Instant Access — ${price:.0f}</a>
</div>
<div class="container">
  <div class="section">
    <h2>What's Inside</h2>
    <ul>
      <li>✅ 50 ready-to-use ChatGPT / Claude prompts</li>
      <li>✅ Designed specifically for <strong>{name.replace(' AI Prompts','').replace(' Boost','').replace(' Aid','')}</strong> professionals</li>
      <li>✅ Instant digital download (TXT file)</li>
      <li>✅ Works with ChatGPT, Claude, Gemini</li>
      <li>✅ Lifetime access + free updates</li>
    </ul>
    <div class="price">${price:.0f} <span class="badge">One-time payment</span></div>
    <a class="cta" href="{url}" rel="nofollow" target="_blank">Buy Now on Gumroad</a>
  </div>
  <div class="section">
    <h2>Who Is This For?</h2>
    <p>This prompt pack is built for anyone who wants to <strong>save time</strong> and work smarter using AI.
    Whether you're a beginner or experienced professional, these prompts give you an immediate advantage.</p>
  </div>
  <div class="section">
    <h2>Sample Prompts</h2>
    <ul>
      <li>"Act as an expert in [field]. Help me [specific task] by giving me [format]..."</li>
      <li>"Create a [content type] that [goal] for [audience]..."</li>
      <li>"Analyze [situation] and give me 5 actionable steps to [outcome]..."</li>
    </ul>
    <p style="margin-top:16px"><em>50 prompts like these, tailored to {name}.</em></p>
  </div>
</div>
"""
    html += PAGE_FOOT.format(site_url=SITE_URL)
    return html


# ─── 日本語記事を静的HTMLに変換 ────────────────────────────────────────

def _article_page(title: str, body: str) -> str:
    desc = body[:120].replace("\n", " ").strip() + "..."
    # Markdownの見出し/強調を簡易変換
    body_html = re.sub(r"^# .+\n", "", body, count=1)
    body_html = re.sub(r"## (.+)", r"<h2>\1</h2>", body_html)
    body_html = re.sub(r"### (.+)", r"<h3>\1</h3>", body_html)
    body_html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", body_html)
    body_html = re.sub(r"\n\n", "</p><p>", body_html)
    body_html = f"<p>{body_html}</p>"

    html = PAGE_HEAD.format(lang="ja", title=f"{title} | AI Holdings", description=desc)
    html += f"""
<div class="hero" style="padding:40px 20px">
  <h1 style="font-size:1.7em">{title}</h1>
</div>
<div class="container">
  <div class="section">
    {body_html}
  </div>
  <div class="section" style="background:#e8f0fe">
    <h2>関連ツール</h2>
    <p>📊 毎日AI投資シグナルを無料配信 → <a href="https://t.me/+yUiqVJi2uNFiOTA1">Telegramチャンネル</a></p>
    <p>🛠️ AIプロダクティビティツールキット → <a href="https://ryuumg.gumroad.com/l/akikab" target="_blank">Gumroad</a></p>
  </div>
</div>
"""
    html += PAGE_FOOT.format(site_url=SITE_URL)
    return html


# ─── サイトマップ生成 ────────────────────────────────────────────────

def _generate_sitemap(urls: list[str]) -> str:
    items = "\n".join(
        f"  <url><loc>{u}</loc><changefreq>weekly</changefreq></url>"
        for u in urls
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{items}
</urlset>"""


def _ping_search_engines(sitemap_url: str):
    for url in [
        f"https://www.google.com/ping?sitemap={sitemap_url}",
        f"https://www.bing.com/ping?sitemap={sitemap_url}",
    ]:
        try:
            urllib.request.urlopen(url, timeout=5)
            print(f"  Ping: {url[:60]}")
        except Exception:
            pass


# ─── メイン ──────────────────────────────────────────────────────────

def main():
    print("[pages_publisher] GitHub Pages生成開始")
    BLOG_DIR.mkdir(parents=True, exist_ok=True)
    all_urls = [SITE_URL + "/"]
    pages_generated = 0

    # 1. Gumroad商品ランディングページ
    products = _fetch_products()
    print(f"  Gumroad商品: {len(products)}件")
    prod_dir = BLOG_DIR / "products"
    prod_dir.mkdir(exist_ok=True)
    for p in products:
        slug = re.sub(r"[^a-z0-9]+", "-", p.get("name", "product").lower()).strip("-")
        out  = prod_dir / f"{slug}.html"
        out.write_text(_product_page(p), encoding="utf-8")
        all_urls.append(f"{SITE_URL}/blog/products/{slug}.html")
        pages_generated += 1
        print(f"  ✅ {p['name']} → blog/products/{slug}.html")

    # 2. 日本語記事を静的HTML化（最新50件）
    art_dir = BLOG_DIR / "articles"
    art_dir.mkdir(exist_ok=True)
    article_count = 0
    if NOTE_OUT.exists():
        for f in sorted(NOTE_OUT.glob("**/*.md"), reverse=True)[:50]:
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
                lines   = content.splitlines()
                title   = lines[0].lstrip("# ").strip() if lines else ""
                if not title or len(title) < 5:
                    continue
                slug = re.sub(r"[^\w]", "-", title[:40]).strip("-")
                out  = art_dir / f"{slug}.html"
                if out.exists():
                    continue
                out.write_text(_article_page(title, content), encoding="utf-8")
                all_urls.append(f"{SITE_URL}/blog/articles/{slug}.html")
                article_count += 1
            except Exception as e:
                print(f"  記事変換失敗: {f.name} — {e}")
    print(f"  記事HTML: {article_count}件生成")
    pages_generated += article_count

    # 3. サイトインデックスページ
    product_links = "".join(
        f'<li><a href="products/{re.sub(r"[^a-z0-9]+", "-", p.get("name","").lower()).strip("-")}.html">'
        f'{p.get("name","")} — ${p.get("price",0)/100:.0f}</a></li>'
        for p in products
    )
    index_html = PAGE_HEAD.format(
        lang="en",
        title="AI Productivity Tools | AI Holdings",
        description="AI prompt packs and productivity tools for professionals. Save time, work smarter.",
    )
    index_html += f"""
<div class="hero">
  <h1>AI Productivity Toolkit</h1>
  <p>50 ready-to-use AI prompts for every professional niche. Instant download.</p>
  <a class="cta" href="https://ryuumg.gumroad.com" target="_blank">Browse All Products</a>
</div>
<div class="container">
  <div class="section">
    <h2>Products</h2>
    <ul>{product_links}</ul>
  </div>
  <div class="section">
    <h2>Free Guides — 15 Prompts Each</h2>
    <ul>
      <li><a href="guides/chatgpt-prompts-for-adhd.html">ChatGPT Prompts for ADHD</a> — Beat procrastination &amp; build focus</li>
      <li><a href="guides/chatgpt-prompts-for-etsy-sellers.html">ChatGPT Prompts for Etsy Sellers</a> — Better listings, more sales</li>
      <li><a href="guides/chatgpt-prompts-for-content-creators.html">ChatGPT Prompts for Content Creators</a> — Go viral faster</li>
      <li><a href="guides/ai-prompts-for-side-hustles.html">AI Prompts for Side Hustles</a> — Launch &amp; scale to $2K+/month</li>
      <li><a href="guides/chatgpt-prompts-for-graphic-designers.html">ChatGPT Prompts for Graphic Designers</a> — Less admin, more design</li>
      <li><a href="guides/chatgpt-prompts-for-procreate-artists.html">ChatGPT Prompts for Procreate Artists</a> — Composition, style &amp; income</li>
      <li><a href="guides/chatgpt-prompts-for-freelancers.html">ChatGPT Prompts for Freelancers</a> — Win clients &amp; charge more</li>
      <li><a href="guides/chatgpt-prompts-for-writers.html">ChatGPT Prompts for Writers</a> — Beat blocks &amp; write faster</li>
      <li><a href="guides/chatgpt-prompts-for-social-media-managers.html">ChatGPT Prompts for Social Media Managers</a> — Create faster, report smarter</li>
      <li><a href="guides/chatgpt-prompts-for-small-business-owners.html">ChatGPT Prompts for Small Business Owners</a> — Marketing, operations &amp; growth</li>
      <li><a href="guides/chatgpt-prompts-for-virtual-assistants.html">ChatGPT Prompts for Virtual Assistants</a> — Handle more work in less time</li>
      <li><a href="guides/chatgpt-prompts-for-fitness-coaches.html">ChatGPT Prompts for Fitness Coaches</a> — Better programs, more clients</li>
      <li><a href="guides/chatgpt-prompts-for-photographers.html">ChatGPT Prompts for Photographers</a> — Less admin, more shooting</li>
      <li><a href="guides/chatgpt-prompts-for-hr-professionals.html">ChatGPT Prompts for HR Professionals</a> — Recruit faster, manage better</li>
      <li><a href="guides/chatgpt-prompts-for-life-coaches.html">ChatGPT Prompts for Life Coaches</a> — Attract clients &amp; grow your practice</li>
      <li><a href="guides/chatgpt-prompts-for-accountants.html">ChatGPT Prompts for Accountants</a> — Better client communication, faster work</li>
      <li><a href="guides/chatgpt-prompts-for-lawyers.html">ChatGPT Prompts for Lawyers</a> — Clear communication, stronger practice</li>
      <li><a href="guides/chatgpt-prompts-for-therapists.html">ChatGPT Prompts for Therapists</a> — Less admin, more clinical energy</li>
      <li><a href="guides/chatgpt-prompts-for-nurses.html">ChatGPT Prompts for Nurses</a> — Better patient education &amp; career growth</li>
      <li><a href="guides/chatgpt-prompts-for-event-planners.html">ChatGPT Prompts for Event Planners</a> — Better proposals, smoother events</li>
      <li><a href="guides/chatgpt-prompts-for-real-estate-investors.html">ChatGPT Prompts for Real Estate Investors</a> — Analyze deals, manage tenants, scale</li>
      <li><a href="guides/chatgpt-prompts-for-executive-assistants.html">ChatGPT Prompts for Executive Assistants</a> — Better briefings, executive-level comms</li>
      <li><a href="guides/chatgpt-prompts-for-project-managers.html">ChatGPT Prompts for Project Managers</a> — Better plans, fewer crises</li>
      <li><a href="guides/chatgpt-prompts-for-consultants.html">ChatGPT Prompts for Consultants</a> — Win clients, deliver more value</li>
      <li><a href="guides/chatgpt-prompts-for-digital-marketers.html">ChatGPT Prompts for Digital Marketers</a> — Better ads, campaigns, and results</li>
      <li><a href="guides/chatgpt-prompts-for-personal-finance.html">ChatGPT Prompts for Personal Finance</a> — Budget, invest, and build wealth</li>
      <li><a href="guides/chatgpt-prompts-for-nonprofit-managers.html">ChatGPT Prompts for Nonprofit Managers</a> — Grant writing, donor comms, impact</li>
      <li><a href="guides/chatgpt-prompts-for-personal-trainers.html">ChatGPT Prompts for Personal Trainers</a> — Programs, clients, and business growth</li>
      <li><a href="guides/chatgpt-prompts-for-youtube-creators.html">ChatGPT Prompts for YouTube Creators</a> — Scripts, titles, thumbnails, growth</li>
      <li><a href="guides/chatgpt-prompts-for-amazon-sellers.html">ChatGPT Prompts for Amazon Sellers</a> — Listings, reviews, PPC, FBA scaling</li>
      <li><a href="guides/chatgpt-prompts-for-copywriters.html">ChatGPT Prompts for Copywriters</a> — Headlines, sales pages, client wins</li>
      <li><a href="guides/chatgpt-prompts-for-ux-designers.html">ChatGPT Prompts for UX Designers</a> — Research, rationale, stakeholders, career</li>
      <li><a href="guides/chatgpt-prompts-for-podcasters.html">ChatGPT Prompts for Podcasters</a> — Show notes, guests, growth, monetization</li>
      <li><a href="guides/chatgpt-prompts-for-restaurant-owners.html">ChatGPT Prompts for Restaurant Owners</a> — Menus, reviews, marketing, operations</li>
      <li><a href="guides/chatgpt-prompts-for-product-managers.html">ChatGPT Prompts for Product Managers</a> — PRDs, roadmaps, stakeholders, career</li>
      <li><a href="guides/chatgpt-prompts-for-ecommerce-sellers.html">ChatGPT Prompts for Ecommerce Sellers</a> — Product pages, ads, emails, scaling</li>
      <li><a href="guides/chatgpt-prompts-for-interior-designers.html">ChatGPT Prompts for Interior Designers</a> — Proposals, concepts, clients, growth</li>
      <li><a href="guides/chatgpt-prompts-for-financial-advisors.html">ChatGPT Prompts for Financial Advisors</a> — Client comms, marketing, practice growth</li>
      <li><a href="guides/chatgpt-prompts-for-insurance-agents.html">ChatGPT Prompts for Insurance Agents</a> — Prospecting, retention, referrals, growth</li>
      <li><a href="guides/chatgpt-prompts-for-dentists.html">ChatGPT Prompts for Dentists</a> — Patient comms, reviews, marketing, retention</li>
      <li><a href="guides/chatgpt-prompts-for-sales-professionals.html">ChatGPT Prompts for Sales Professionals</a> — Cold emails, objections, closing, career</li>
      <li><a href="guides/chatgpt-prompts-for-web-designers.html">ChatGPT Prompts for Web Designers</a> — Proposals, clients, pricing, recurring income</li>
      <li><a href="guides/chatgpt-prompts-for-online-course-creators.html">ChatGPT Prompts for Online Course Creators</a> — Curriculum, sales pages, launches, scaling</li>
      <li><a href="guides/chatgpt-prompts-for-chiropractors.html">ChatGPT Prompts for Chiropractors</a> — Patient comms, local marketing, practice growth</li>
      <li><a href="guides/chatgpt-prompts-for-nutritionists.html">ChatGPT Prompts for Nutritionists &amp; Dietitians</a> — Client communication, practice marketing, content</li>
      <li><a href="guides/chatgpt-prompts-for-mortgage-brokers.html">ChatGPT Prompts for Mortgage Brokers</a> — Client education, referral partners, lead generation</li>
      <li><a href="guides/chatgpt-prompts-for-data-analysts.html">ChatGPT Prompts for Data Analysts</a> — Reports, stakeholder comms, career growth</li>
      <li><a href="guides/chatgpt-prompts-for-recruiters.html">ChatGPT Prompts for Recruiters</a> — Job descriptions, sourcing, candidate experience</li>
      <li><a href="guides/chatgpt-prompts-for-brand-strategists.html">ChatGPT Prompts for Brand Strategists</a> — Positioning, messaging, client deliverables</li>
      <li><a href="guides/chatgpt-prompts-for-startup-founders.html">ChatGPT Prompts for Startup Founders</a> — Pitching, investors, customer growth, operations</li>
      <li><a href="guides/chatgpt-prompts-for-career-coaches.html">ChatGPT Prompts for Career Coaches</a> — Client attraction, sessions, practice growth</li>
      <li><a href="guides/chatgpt-prompts-for-cybersecurity-professionals.html">ChatGPT Prompts for Cybersecurity Professionals</a> — Risk communication, awareness, documentation</li>
      <li><a href="guides/chatgpt-prompts-for-technical-writers.html">ChatGPT Prompts for Technical Writers</a> — Docs, style guides, collaboration, career</li>
    </ul>
  </div>
  <div class="section">
    <h2>Free Tools</h2>
    <ul>
      <li><a href="tools/prompt-sampler.html">Free ChatGPT Prompt Generator</a> — Get 5 free AI prompts for your niche</li>
      <li><a href="tools/side-hustle-calculator.html">Side Hustle Income Calculator</a> — Estimate your monthly earnings potential</li>
    </ul>
  </div>
  <div class="section">
    <h2>Free Resources</h2>
    <p>📊 Daily AI investment signals → <a href="https://t.me/+yUiqVJi2uNFiOTA1">Telegram Channel (Free)</a></p>
  </div>
</div>"""
    index_html += PAGE_FOOT.format(site_url=SITE_URL)
    (BLOG_DIR / "index.html").write_text(index_html, encoding="utf-8")
    all_urls.append(f"{SITE_URL}/blog/")
    print("  ✅ blog/index.html生成")

    # 3b. 英語記事ページをサイトマップに追加
    en_dir = BLOG_DIR / "en"
    if en_dir.exists():
        for f in sorted(en_dir.glob("*.html")):
            all_urls.append(f"{SITE_URL}/blog/en/{f.name}")
        print(f"  英語記事: {len(list(en_dir.glob('*.html')))}件サイトマップ追加")

    # 3c. ツールページをサイトマップに追加
    all_urls.append(f"{SITE_URL}/blog/tools/prompt-sampler.html")
    all_urls.append(f"{SITE_URL}/blog/tools/side-hustle-calculator.html")
    all_urls.append(f"{SITE_URL}/blog/tools/ai-writing-assistant.html")

    # 3d. ガイド記事をサイトマップに追加
    guides_dir = BLOG_DIR / "guides"
    if guides_dir.exists():
        for f in sorted(guides_dir.glob("*.html")):
            all_urls.append(f"{SITE_URL}/blog/guides/{f.name}")
    all_urls.append(f"{SITE_URL}/start.html")

    # 4. サイトマップ生成
    sitemap = _generate_sitemap(all_urls)
    (BLOG_DIR / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    print(f"  ✅ sitemap.xml ({len(all_urls)}URL)")

    # 5. Search Engine Ping
    _ping_search_engines(f"{SITE_URL}/blog/sitemap.xml")

    print(f"[完了] {pages_generated}ページ生成")


if __name__ == "__main__":
    main()
