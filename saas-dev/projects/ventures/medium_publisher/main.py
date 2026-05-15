"""
ventures/medium_publisher/main.py
毎日実行: note記事を英訳 → Medium投稿 → Geminiで翻訳戦略を最適化
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.optimizer import optimize
from shared.metrics import load_state, save_state, record_performance, apply_optimization
from translator import translate_article, pick_next_article
from publisher import publish, publish_hashnode, _get_api_key

STATE_PATH  = Path(__file__).parent / "state.json"
NOTE_OUTPUT = Path(__file__).parent.parent.parent.parent.parent / "note-biz" / "output"

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

    # Step3: Dev.to投稿
    try:
        url = publish(
            translated["title"], translated.get("subtitle", ""),
            translated["body"], translated.get("tags", []), api_key
        )
        print(f"  投稿完了: {url}")
        state.setdefault("posted_titles", []).append(article["title"])
        state["articles_published"] = state.get("articles_published", 0) + 1
        status = "success"
    except Exception as e:
        print(f"  [ERROR] {e}")
        url = None
        status = "failed"

    # Step3b: Hashnode同時投稿
    hn_key  = os.environ.get("HASHNODE_API_KEY", "")
    hn_pub  = os.environ.get("HASHNODE_PUBLICATION_ID", "")
    if hn_key and hn_pub and status == "success":
        try:
            hn_url = publish_hashnode(
                translated["title"], translated["body"],
                translated.get("tags", []), hn_key, hn_pub,
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
