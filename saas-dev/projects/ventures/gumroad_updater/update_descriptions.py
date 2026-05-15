"""
Gumroad製品説明文一括更新スクリプト
python update_descriptions.py
"""
import os
import json
import urllib.request
import urllib.parse
from pathlib import Path

env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
TOKEN = os.environ.get("GUMROAD_ACCESS_TOKEN", "")
if not TOKEN and env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("GUMROAD_ACCESS_TOKEN="):
            TOKEN = line.split("=", 1)[1].strip()

NEW_DESCS = {
"Etsy Seller Boost": """Struggling to get your Etsy listings to show up in search — or getting views but no sales?

This prompt pack gives you 50 battle-tested ChatGPT prompts built specifically for Etsy sellers. No fluff, no generic marketing tips — just prompts you paste in and get results from.

WHAT'S INSIDE:
✅ 15 prompts for SEO-optimized titles and tags that actually rank
✅ 10 prompts for product descriptions that convert browsers into buyers
✅ 8 prompts for customer message responses (saves hours every week)
✅ 7 prompts for shop branding, story, and policies
✅ 6 prompts for pricing research and competitor analysis
✅ 4 prompts for your About page and seller bio

HOW IT WORKS: Open ChatGPT or Claude → paste a prompt → fill in the [brackets] → polished result in 60 seconds.

WHO IT'S FOR: Etsy sellers at any stage — first shop setup to optimizing 100+ listings.

WHAT YOU GET: One TXT file. Instant download. Works with ChatGPT, Claude, Gemini. Lifetime access.""",

"Etsy Success Boost": """You've got the shop. You've got the products. But you're still not hitting the growth you want.

This advanced prompt pack is for Etsy sellers who are past the basics and ready to scale. 50 prompts focused on strategy, marketing, and turning a part-time shop into a real income source.

WHAT'S INSIDE:
✅ 12 prompts for seasonal campaign planning and launch calendars
✅ 10 prompts for email list building and buyer follow-up sequences
✅ 8 prompts for competitor analysis and finding untapped niches
✅ 8 prompts for social media content that drives shop traffic
✅ 7 prompts for pricing strategy, bundle deals, and upsells
✅ 5 prompts for scaling to your first $5K month

THE DIFFERENCE: Unlike basic listing prompts, these are about building a business — repeat customers, steady traffic, compounding income.

WHO IT'S FOR: Etsy sellers with an established shop ready to hit $2K-$10K/month.

WHAT YOU GET: One TXT file. Instant download. Lifetime access.""",

"ADHD Unlocked": """Generic productivity advice doesn't work for ADHD brains. This does.

50 ChatGPT prompts designed to work with how your brain actually functions — not against it.

WHAT'S INSIDE:
✅ 12 prompts for breaking overwhelming tasks into micro-steps you'll actually start
✅ 10 prompts for building routines that stick (habit-stacking, dopamine hooks, body-doubling)
✅ 9 prompts for managing time blindness and deadline anxiety
✅ 8 prompts for handling rejection sensitivity and emotional regulation
✅ 7 prompts for focus systems designed around ADHD (not generic Pomodoro)
✅ 4 prompts for communicating your needs to employers and clients

WHY THIS WORKS: Each prompt is designed around ADHD-specific challenges: task paralysis, hyperfocus, working memory limits, and dopamine-seeking. Not a generic to-do template.

WHO IT'S FOR: Adults with ADHD who want to use AI as an external brain.

WHAT YOU GET: One TXT file. Instant download. Works with ChatGPT, Claude, Gemini.""",

"AI Content Boost": """Stop spending 4 hours writing content that gets 12 views.

50 proven ChatGPT prompts for content creators who want to write faster, go viral more consistently, and build an audience that actually buys.

WHAT'S INSIDE:
✅ 10 prompts for scroll-stopping hooks on any platform
✅ 10 prompts for repurposing (turn 1 video into 7 pieces of content)
✅ 8 prompts for headline optimization — test before you publish
✅ 8 prompts for building a 30-day content calendar in under 20 minutes
✅ 7 prompts for audience research and niche positioning
✅ 7 prompts for email, newsletter, and nurture content

PLATFORMS: Instagram, TikTok, YouTube, LinkedIn, Twitter/X, Substack, blog.

WHO IT'S FOR: Creators and personal brands who want to publish consistently without burnout.

WHAT YOU GET: One TXT file. Instant download. Lifetime access.""",

"Viral Content": """Most content dies at 200 views. These prompts are built to break that pattern.

50 ChatGPT prompts reverse-engineered from viral posts across every major platform.

WHAT'S INSIDE:
✅ 12 prompts for opening hooks that trigger the 'keep reading' response
✅ 10 prompts for controversial-but-safe takes that spark shares and comments
✅ 8 prompts for storytelling frameworks (hero's journey, plot twist, confession)
✅ 8 prompts for trend newsjacking — insert your brand into what's already viral
✅ 7 prompts for platform-specific mechanics (TikTok, Twitter threads, IG carousels)
✅ 5 prompts for comment bait and engagement loops

THE INSIGHT: Virality follows patterns. These prompts encode them.

WHO IT'S FOR: Creators, marketers, and brand accounts who want more reach.

WHAT YOU GET: One TXT file. Instant download. Lifetime access.""",

"DesignGenie": """Spend less time on admin. More time designing.

50 AI prompts for graphic designers — covering briefs, client communication, concept development, and business.

WHAT'S INSIDE:
✅ 10 prompts for writing professional creative briefs fast
✅ 10 prompts for client communication — feedback requests, revision scope, pricing
✅ 8 prompts for concept development: color theory, typography, visual hierarchy
✅ 8 prompts for portfolio case studies that win clients
✅ 7 prompts for pricing your work and handling rate negotiations
✅ 7 prompts for social content that showcases your process

WHO IT'S FOR: Freelance and brand designers who want to level up their business side — not just their creative skills.

WHAT YOU GET: One TXT file. Instant download. Works with ChatGPT, Claude, or Gemini.""",

"Procreate AI": """50 AI prompts to push your Procreate work further — faster.

Whether you're stuck on composition, color, or just want fresh ideas, these prompts give you a creative partner that never runs out of direction.

WHAT'S INSIDE:
✅ 10 prompts for composition and focal point decisions
✅ 10 prompts for color palette generation by mood, season, and reference
✅ 8 prompts for character design consistency across poses
✅ 8 prompts for lighting and shadow logic in any style
✅ 7 prompts for developing your unique illustration style
✅ 7 prompts for concept art, thumbnails, and quick studies

HOW TO USE: Describe your piece → paste the prompt → get specific, tailored direction.

WHO IT'S FOR: Procreate artists at any level who want a faster creative brainstorming partner.

WHAT YOU GET: One TXT file. Instant download. Lifetime access.""",

"Procreate Aid": """When you've mastered the basics, you need harder challenges to grow.

50 advanced ChatGPT prompts for Procreate artists ready for professional-level techniques.

WHAT'S INSIDE:
✅ 10 prompts for advanced texture and surface detail
✅ 10 prompts for complex lighting (rim light, subsurface scattering, dramatic shadow)
✅ 8 prompts for character expression sheets and emotional range
✅ 8 prompts for background environments and depth layering
✅ 7 prompts for developing a saleable illustration style
✅ 7 prompts for print-ready specs and commercial use guidance

THE DIFFERENCE FROM PROCREATE AI: These assume you already know the basics. Built for deliberate practice that builds professional-level judgment.

WHO IT'S FOR: Intermediate-to-advanced Procreate artists who want to level up their artistic eye.

WHAT YOU GET: One TXT file. Instant download. Lifetime access.""",

"Procreate Assets": """50 ChatGPT prompts for Procreate artists who want to create, sell, and grow.

Whether you're building a design business, selling on Creative Market, or developing a cohesive visual style — these prompts accelerate the process.

WHAT'S INSIDE:
✅ 10 prompts for pattern design and repeat tile creation
✅ 10 prompts for brush set development and customization
✅ 8 prompts for creating and marketing Procreate asset packs
✅ 8 prompts for brand illustration systems (icons, spot illustrations, mascots)
✅ 7 prompts for licensing, pricing, and platform selection
✅ 7 prompts for client work — brief to final delivery

WHO IT'S FOR: Digital artists who want to turn their Procreate skills into income through asset sales or client work.

WHAT YOU GET: One TXT file. Instant download. Lifetime access.""",
}


def main():
    if not TOKEN:
        print("GUMROAD_ACCESS_TOKEN not set")
        return

    req = urllib.request.Request(
        "https://api.gumroad.com/v2/products",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())

    for p in data.get("products", []):
        name = p["name"]
        pid  = p["id"]
        new_desc = NEW_DESCS.get(name)
        if not new_desc:
            print(f"  [SKIP] {name}")
            continue

        payload = urllib.parse.urlencode({"description": new_desc}).encode("utf-8")
        upd = urllib.request.Request(
            f"https://api.gumroad.com/v2/products/{pid}",
            data=payload,
            method="PUT",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(upd, timeout=15) as r:
            resp = json.loads(r.read())
        ok = resp.get("success", False)
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {name}")

    print("完了")


if __name__ == "__main__":
    main()
