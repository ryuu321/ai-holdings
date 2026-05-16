"""
youtube_shorts/main.py
毎日JST 10:00: 各Gumroad商品向けのYouTube Shortsを自動生成・投稿
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

_ROOT      = Path(__file__).parent.parent.parent.parent.parent
STATE_FILE = Path(__file__).parent / "state.json"
VIDEO_DIR  = Path(__file__).parent / "videos"
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")


# 商品ごとのShorts素材定義（動画ごとに5プロンプトをローテーション）
PRODUCT_SHORTS = [
    {
        "product": "ADHD Unlocked",
        "product_url": "https://ryuumg.gumroad.com/l/akikab",
        "yt_tags": ["ADHD", "ChatGPT", "productivity", "AI", "ADHDproductivity", "ChatGPTprompts"],
        "videos": [
            {
                "title": "5 ChatGPT Prompts for ADHD Focus",
                "subtitle": "Use AI as your external brain",
                "prompts": [
                    {"title": "Beat Task Paralysis", "text": "Break [task] into 5 micro-steps. Make the first step take under 2 minutes."},
                    {"title": "Build a Routine", "text": "Design a morning routine for someone with ADHD. Include dopamine hooks for each step."},
                    {"title": "Time Blindness Fix", "text": "Create a visual timeline for my day with [X hours]. Include buffer time between tasks."},
                    {"title": "Focus Session Planner", "text": "Plan a 90-minute ADHD-friendly work session for [task]. Include breaks and re-entry cues."},
                    {"title": "Emotional Reset", "text": "I'm overwhelmed by [situation]. Give me 3 ADHD-specific strategies to reset and restart."},
                ],
            },
            {
                "title": "5 ChatGPT Prompts to Stop Procrastinating",
                "subtitle": "For ADHD brains that need a nudge",
                "prompts": [
                    {"title": "Minimum Viable Start", "text": "What is the absolute smallest first action I can take on [task]? Must take under 90 seconds."},
                    {"title": "Hyperfocus Redirect", "text": "I'm hyperfocusing on [wrong thing]. Help me create a bridge to redirect to [priority task]."},
                    {"title": "Decision Fatigue Fix", "text": "I can't decide between [options]. Give me a simple framework to decide in under 3 minutes."},
                    {"title": "Accountability Script", "text": "Write me a body-doubling script to say aloud to start working on [task] right now."},
                    {"title": "Overwhelm Triage", "text": "I have [X] tasks. Sort them by: must do today, can wait, can delete. Be ruthless."},
                ],
            },
        ],
    },
    {
        "product": "AI Content Boost",
        "product_url": "https://ryuumg.gumroad.com/l/qhanl",
        "yt_tags": ["ContentCreation", "ChatGPT", "AI", "ContentCreator", "SocialMedia", "viral"],
        "videos": [
            {
                "title": "5 ChatGPT Hooks That Stop the Scroll",
                "subtitle": "Copy these for your next post",
                "prompts": [
                    {"title": "Curiosity Gap Hook", "text": "Write 5 hooks for [topic] that create a curiosity gap. Readers can't stop without knowing more."},
                    {"title": "Contrarian Take", "text": "Write a contrarian take on [common belief in niche]. Make it provocative but backed by logic."},
                    {"title": "Relatable Pain Hook", "text": "Write a hook for [topic] that starts with a pain my audience feels every single day."},
                    {"title": "Shocking Stat Opener", "text": "Find or create a shocking stat about [topic] to use as a hook. Verify it makes logical sense."},
                    {"title": "Story Opener", "text": "Write a 2-sentence story opener for [topic] that puts readers IN the moment, not observing it."},
                ],
            },
        ],
    },
    {
        "product": "Etsy Seller Boost",
        "product_url": "https://ryuumg.gumroad.com/l/nnijeb",
        "yt_tags": ["Etsy", "EtsySeller", "ChatGPT", "AI", "EtsySEO", "EtsyTips"],
        "videos": [
            {
                "title": "5 ChatGPT Prompts Every Etsy Seller Needs",
                "subtitle": "Write listings that actually rank",
                "prompts": [
                    {"title": "SEO Title Writer", "text": "Write an Etsy title for [product] that leads with [main keyword] and is under 140 characters."},
                    {"title": "Description Converter", "text": "Rewrite this Etsy description to lead with benefits, not features: [paste description]."},
                    {"title": "Tag Generator", "text": "Generate 13 Etsy tags for [product]. Mix broad and long-tail. Avoid repeating title words."},
                    {"title": "Customer FAQ Writer", "text": "Write 5 FAQs and answers for my Etsy listing about [product]. Address shipping, materials, size."},
                    {"title": "Review Response", "text": "A customer left this review: [review]. Write a warm, professional response that invites them back."},
                ],
            },
        ],
    },
    {
        "product": "DesignGenie",
        "product_url": "https://ryuumg.gumroad.com/l/zkiwh",
        "yt_tags": ["GraphicDesign", "ChatGPT", "AI", "FreelanceDesign", "DesignTools"],
        "videos": [
            {
                "title": "5 ChatGPT Prompts for Graphic Designers",
                "subtitle": "Less admin, more design time",
                "prompts": [
                    {"title": "Creative Brief Generator", "text": "Create a creative brief for [project type] for [client description]. Include goals and constraints."},
                    {"title": "Color Palette Strategist", "text": "Recommend a color palette for a [brand type] that feels [adjective]. Include hex codes and why."},
                    {"title": "Client Feedback Decoder", "text": "My client said: [vague feedback]. What are they probably asking for? Give me 3 interpretations."},
                    {"title": "Portfolio Case Study", "text": "Write a portfolio case study for [project]. Focus on the problem, my process, and the outcome."},
                    {"title": "Price Justification", "text": "A client thinks my [service] is expensive at $[price]. Write a response that explains the value."},
                ],
            },
        ],
    },
    {
        "product": "Viral Content",
        "product_url": "https://ryuumg.gumroad.com/l/rboqqr",
        "yt_tags": ["ViralContent", "ChatGPT", "ContentMarketing", "AI", "SocialMedia"],
        "videos": [
            {
                "title": "5 Viral Content Formulas (With Prompts)",
                "subtitle": "Reverse-engineered from top posts",
                "prompts": [
                    {"title": "The Plot Twist", "text": "Write a [platform] post about [topic] that starts with one thing and ends with a complete reversal."},
                    {"title": "Trend Newsjacker", "text": "I'm in the [niche] space. Help me connect [trending topic] to my audience's interests naturally."},
                    {"title": "Tag-a-Friend Trigger", "text": "Write a post about [topic] designed to make people tag a specific type of friend in comments."},
                    {"title": "Hot Take Factory", "text": "Give me 5 hot takes about [topic] that are provocative but defensible. Include a counter-argument."},
                    {"title": "The Share-Worthy Stat", "text": "Find or derive a surprising statistic about [topic] that would make someone screenshot and share."},
                ],
            },
        ],
    },
    {
        "product": "Procreate AI",
        "product_url": "https://ryuumg.gumroad.com/l/yugogd",
        "yt_tags": ["Procreate", "DigitalArt", "ChatGPT", "AI", "ProcreateArt", "Illustration"],
        "videos": [
            {
                "title": "5 ChatGPT Prompts for Procreate Artists",
                "subtitle": "Use AI as your creative director",
                "prompts": [
                    {"title": "Composition Generator", "text": "Suggest 5 composition ideas for a Procreate illustration of [subject]. Include focal point and flow."},
                    {"title": "Color Palette by Mood", "text": "Give me a color palette for an illustration with a [mood] vibe. Include 5 hex codes and roles."},
                    {"title": "Style Influences", "text": "I love [artist 1] and [artist 2]. What visual elements could I combine to create my own style?"},
                    {"title": "Art Series Planner", "text": "Design a 6-piece illustration series about [theme]. Each piece should stand alone but connect."},
                    {"title": "Commission Pricing", "text": "I do [type] commissions in Procreate at [hours/piece]. Help me build a fair pricing sheet."},
                ],
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
    return {"published_dates": [], "video_index": 0, "total": 0}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _pick_video(state: dict) -> tuple[dict, dict] | None:
    idx = state.get("video_index", 0)
    all_videos = []
    for product in PRODUCT_SHORTS:
        for video in product["videos"]:
            all_videos.append((product, video))

    if not all_videos:
        return None
    product, video = all_videos[idx % len(all_videos)]
    state["video_index"] = (idx + 1) % len(all_videos)
    return product, video


def _build_description(product: dict, video: dict, yt_url: str = "") -> str:
    prompts_text = "\n\n".join(
        f"📌 {p['title']}:\n{p['text']}"
        for p in video["prompts"]
    )
    tags = " ".join(f"#{t}" for t in product["yt_tags"])
    return f"""{video['title']}

Save this for later! Here are 5 prompts you can copy-paste right now.

{prompts_text}

---
🛍️ Get 50 more {product['product']} prompts (instant download):
{product['product_url']}

🆓 Free AI prompt guides:
https://ryuu321.github.io/ai-holdings/start.html

#Shorts #ChatGPT #AI {tags}"""


def main():
    print(f"\n{'='*50}")
    print("[youtube_shorts] YouTube Shorts自動投稿 開始")

    state = _load_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if today in state.get("published_dates", []):
        print(f"  [SKIP] 本日({today})は既に投稿済み")
        return

    result = _pick_video(state)
    if not result:
        print("  [SKIP] 動画素材なし")
        return

    product, video = result
    print(f"  商品: {product['product']}")
    print(f"  動画: {video['title']}")

    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", video["title"].lower())[:40]
    output_path = VIDEO_DIR / f"{today}-{slug}.mp4"

    from video_generator import generate_video
    ok = generate_video(
        title=video["title"],
        subtitle=video["subtitle"],
        prompts=video["prompts"],
        product_name=product["product"],
        product_url=product["product_url"],
        output_path=output_path,
    )

    yt_url = ""
    if ok:
        from uploader import upload_video
        description = _build_description(product, video)
        yt_url = upload_video(
            video_path=output_path,
            title=video["title"],
            description=description,
            tags=product["yt_tags"] + ["ChatGPT", "AI", "prompts", "Shorts"],
        )
        # 動画ファイルは削除（リポジトリ肥大化防止）
        try:
            output_path.unlink()
        except Exception:
            pass

    state.setdefault("published_dates", []).append(today)
    state["total"] = state.get("total", 0) + 1
    _save_state(state)

    print(f"[完了] 通算{state['total']}本{f' → {yt_url}' if yt_url else ' (要OAuth設定)'}")


if __name__ == "__main__":
    main()
