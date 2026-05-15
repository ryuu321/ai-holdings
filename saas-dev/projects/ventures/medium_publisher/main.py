"""
ventures/medium_publisher/main.py
毎日実行: note記事を英訳 → Medium投稿 → Geminiで翻訳戦略を最適化
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.optimizer import optimize
from shared.metrics import load_state, save_state, record_performance, apply_optimization
from translator import translate_article, pick_next_article
from publisher import publish, publish_hashnode, _get_api_key

STATE_PATH  = Path(__file__).parent / "state.json"
NOTE_OUTPUT = Path(__file__).parent.parent.parent.parent.parent / "note-biz" / "output"
SITE_URL    = "https://ryuu321.github.io/ai-holdings"
EN_BLOG_DIR = Path(__file__).parent.parent.parent.parent.parent / "docs" / "blog" / "en"

DEFAULT_STATE = {
    "venture": "medium_publisher",
    "params": {
        "priority_genre": None,
        "writing_style": "conversational and data-driven",
        "target_length": "900-1300 words",
    },
    "performance_history": [],
    "learnings": [],
    "last_optimized": None,
    "posted_titles": [],
    "articles_published": 0,
}


_PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} | AI Holdings</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta name="robots" content="index, follow">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a2e;background:#f8f9ff;line-height:1.7}}
.hero{{background:linear-gradient(135deg,#0f3460 0%,#16213e 100%);color:#fff;padding:40px 20px;text-align:center}}
.hero h1{{font-size:1.9em;margin-bottom:8px;line-height:1.3}}
.container{{max-width:820px;margin:0 auto;padding:32px 20px}}
.body-text h2{{font-size:1.4em;color:#0f3460;margin:24px 0 10px;border-left:3px solid #f5a623;padding-left:10px}}
.body-text p{{margin:12px 0}}
.body-text ul{{padding-left:20px;margin:10px 0}}
.body-text li{{margin:5px 0}}
.cta-box{{background:#fff3cd;border:1px solid #f5a623;border-radius:8px;padding:20px;margin-top:32px}}
.cta-box a{{color:#0f3460;font-weight:700}}
footer{{text-align:center;padding:24px;color:#666;font-size:.85em}}
</style>
</head>
<body>
<div class="hero"><h1>{title}</h1></div>
<div class="container"><div class="body-text">
"""

_PAGE_FOOT = """</div></div>
<footer><p>© 2026 AI Holdings | <a href="{site_url}">Home</a></p></footer>
</body></html>"""


def _md_to_html(md: str) -> str:
    import re as _re
    h = _re.sub(r"^## (.+)$", r"<h2>\1</h2>", md, flags=_re.MULTILINE)
    h = _re.sub(r"^### (.+)$", r"<h3>\1</h3>", h, flags=_re.MULTILINE)
    h = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", h)
    h = _re.sub(r"\*(.+?)\*", r"<em>\1</em>", h)
    h = _re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', h)
    h = _re.sub(r"\n\n+", "</p><p>", h)
    return f"<p>{h}</p>"


def _build_en_html(translated: dict, canonical_url: str) -> str:
    title = translated.get("title", "")
    subtitle = translated.get("subtitle", "")
    body_md = translated.get("body", "")
    desc = subtitle or body_md[:120].replace("\n", " ").strip() + "..."
    html = _PAGE_HEAD.format(title=title, desc=desc, canonical=canonical_url)
    if subtitle:
        html += f"<p><em>{subtitle}</em></p>\n"
    html += _md_to_html(body_md)
    html += _PAGE_FOOT.format(site_url=SITE_URL)
    return html


def main():
    print(f"\n{'='*50}")
    print("[medium_publisher] Medium投稿 開始")
    state = load_state(STATE_PATH) or DEFAULT_STATE
    api_key = _get_api_key()

    if not api_key:
        print("  [SKIP] MEDIUM_API_KEY 未設定")
        return

    # Step1: 未翻訳の最良記事を選ぶ
    article = pick_next_article(NOTE_OUTPUT, state.get("posted_titles", []), state["params"])
    if not article:
        print("  [SKIP] 翻訳可能な記事なし（note-autoの記事が溜まってから再実行）")
        return

    print(f"  記事: {article['title']}")
    print(f"  ジャンル: {article['genre']}")

    # Step2: 英訳
    print("  翻訳中...")
    translated = translate_article(article, state["params"])
    print(f"  英題: {translated['title']}")

    # Step3: GitHub Pages英語記事を先に保存 → canonical_url確立
    en_slug = re.sub(r"[^a-z0-9]+", "-", translated["title"].lower())[:60].strip("-")
    canonical_url = f"{SITE_URL}/blog/en/{en_slug}.html"
    try:
        EN_BLOG_DIR.mkdir(parents=True, exist_ok=True)
        en_html = _build_en_html(translated, canonical_url)
        (EN_BLOG_DIR / f"{en_slug}.html").write_text(en_html, encoding="utf-8")
        print(f"  ✅ GitHub Pages保存: blog/en/{en_slug}.html")
    except Exception as e:
        print(f"  [HTML SKIP] {e}")
        canonical_url = ""

    # Step3b: Dev.to投稿
    try:
        url = publish(
            translated["title"], translated.get("subtitle", ""),
            translated["body"], translated.get("tags", []), api_key,
            canonical_url=canonical_url,
        )
        print(f"  投稿完了: {url}")
        state.setdefault("posted_titles", []).append(article["title"])
        state["articles_published"] = state.get("articles_published", 0) + 1
        status = "success"
    except Exception as e:
        print(f"  [ERROR] {e}")
        url = None
        status = "failed"

    # Step3c: Hashnode同時投稿
    hn_key  = os.environ.get("HASHNODE_API_KEY", "")
    hn_pub  = os.environ.get("HASHNODE_PUBLICATION_ID", "")
    if hn_key and hn_pub and status == "success":
        try:
            hn_url = publish_hashnode(
                translated["title"], translated["body"],
                translated.get("tags", []), hn_key, hn_pub,
                canonical_url=canonical_url,
            )
            print(f"  Hashnode投稿完了: {hn_url}")
        except Exception as e:
            print(f"  [Hashnode SKIP] {e}")

    # Step4: メトリクス記録
    state = record_performance(state, {
        "genre": article["genre"],
        "title_en": translated.get("title", ""),
        "status": status,
        "articles_total": state.get("articles_published", 0),
    })

    # Step5: 7記事以上でGemini最適化
    if state.get("articles_published", 0) >= 7:
        print("  [最適化] Gemini分析中...")
        opt = optimize("medium_publisher", state)
        state = apply_optimization(state, opt)
        print(f"  洞察: {opt['insight']}")
        print(f"  次のアクション: {opt['action']}")

    save_state(STATE_PATH, state)
    print(f"[完了] 通算{state.get('articles_published', 0)}記事 | {status.upper()}")


if __name__ == "__main__":
    main()
