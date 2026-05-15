"""
note記事（日本語）→ Medium記事（英語）に翻訳・再構成
"""
import json
import os
import time
from pathlib import Path

try:
    from google import genai
except ImportError:
    print("pip install google-genai")
    exit(1)

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip()
                break

client = genai.Client(api_key=API_KEY)


GUMROAD_PRODUCTS = {
    "Personal Finance": {
        "url": "https://ryuumg.gumroad.com/l/ndtsjv",
        "label": "Personal Finance AI Prompts — 50 ChatGPT prompts to save more & invest smarter",
    },
    "Career Development": {
        "url": "https://app.gumroad.com/d/uNOVzVYiwY3R",
        "label": "ADHD Unlocked — focus system for high-achievers",
    },
    "AI & Productivity": {
        "url": "https://app.gumroad.com/d/uNOVzVYiwY3R",
        "label": "ADHD Unlocked — AI productivity toolkit for high-achievers",
    },
}
_DEFAULT_PRODUCT = {
    "url": "https://app.gumroad.com/d/uNOVzVYiwY3R",
    "label": "ADHD Unlocked — AI focus system for high-achievers",
}


def translate_article(article: dict, params: dict) -> dict:
    style = params.get("writing_style", "conversational and data-driven")
    length = params.get("target_length", "900-1300 words")
    focus = params.get("priority_genre", article.get("genre", ""))

    genre = article.get("genre", focus)
    product = GUMROAD_PRODUCTS.get(genre, _DEFAULT_PRODUCT)
    product_url = product["url"]
    product_label = product["label"]

    prompt = f"""You are a professional English content writer. Convert the Japanese source into a high-quality English article.

Source (Japanese):
Genre: {focus}
Title: {article['title']}
Free section: {article['free_body'][:400]}
Main section: {article['paid_body'][:2000]}

Writing requirements:
- Style: {style}
- Length: {length}
- Rewrite naturally for English readers — NOT a translation
- Use concrete numbers, real examples, actionable steps
- SEO: include primary keyword in title and first paragraph
- IMPORTANT: Use ONLY standard English ASCII characters in the title. No Japanese characters, no special Unicode symbols, no curly quotes — straight ASCII only.

End the body with this exact block (copy verbatim, do not translate):
---
📊 I share daily AI investment signals free on Telegram → https://t.me/+yUiqVJi2uNFiOTA1

🛠️ Grab my full toolkit: [{product_label}]({product_url})

Respond with valid JSON only (no markdown fences, no extra text):
{{
  "title": "Compelling SEO title in plain ASCII English (include a number if natural)",
  "subtitle": "One punchy hook sentence under 120 chars",
  "body": "Full article in Markdown with ## subheadings and bullet points",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]
}}"""

    for attempt in range(4):
        try:
            resp = client.models.generate_content(
                model="gemini-flash-latest",
                contents=prompt,
                config={"temperature": 0.75}
            )
            text = resp.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except Exception as e:
            err = str(e)
            if attempt < 3 and ("429" in err or "503" in err or "RESOURCE_EXHAUSTED" in err):
                wait = 60 * (attempt + 1)
                print(f"  [WAIT] {wait}s リトライ...")
                time.sleep(wait)
            else:
                raise


def pick_next_article(note_output_dir: Path, posted_titles: list, params: dict) -> dict | None:
    priority = params.get("priority_genre")
    md_files = sorted(note_output_dir.glob("*.md"), reverse=True)

    candidates = []
    for f in md_files:
        content = f.read_text(encoding="utf-8", errors="ignore")
        lines = content.splitlines()
        title = lines[0].lstrip("# ").strip() if lines else ""
        if not title or title in posted_titles:
            continue

        # paid_bodyがある記事のみ
        if "<!-- 有料部分 -->" not in content:
            continue

        free_body = ""
        paid_body = ""
        parts = content.split("<!-- 有料部分 -->")
        if "<!-- 無料部分 -->" in parts[0]:
            free_body = parts[0].split("<!-- 無料部分 -->")[1].strip()
        if len(parts) > 1:
            paid_body = parts[1].strip()

        if not paid_body or len(paid_body) < 500:
            continue

        genre = "AI & Productivity"
        if any(k in title for k in ["節約", "NISA", "投資", "貯金", "家計"]):
            genre = "Personal Finance"
        elif any(k in title for k in ["転職", "キャリア", "面接", "年収"]):
            genre = "Career Development"

        candidates.append({
            "title": title,
            "free_body": free_body,
            "paid_body": paid_body,
            "genre": genre,
            "source_file": f.name,
        })

    if not candidates:
        return None

    # priority_genreがあれば優先
    if priority:
        genre_map = {
            "AI副業・ChatGPT活用系": "AI & Productivity",
            "お金・節約・投資入門系": "Personal Finance",
            "就活・転職・キャリア系": "Career Development",
        }
        en_priority = genre_map.get(priority, priority)
        for c in candidates:
            if c["genre"] == en_priority:
                return c

    return candidates[0]
