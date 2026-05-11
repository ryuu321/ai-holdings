"""
note-auto/main.py — リサーチ→記事生成→note投稿 全自動パイプライン
Usage: python main.py --account 1
"""
import json
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

from research import research_topic, mark_book_note_linked
from writer   import generate_article
from poster   import post_article, login

STATE_DIR  = Path(__file__).parent
OUTPUT_DIR = Path(__file__).parent.parent.parent.parent / "note-biz" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_state(account_id: int) -> dict:
    f = STATE_DIR / f"state_{account_id}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"posted_topics": [], "articles": []}


def save_state(account_id: int, state: dict):
    f = STATE_DIR / f"state_{account_id}.json"
    f.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def run(account_id: int):
    import os
    email    = os.environ.get(f"NOTE_EMAIL_{account_id}")
    password = os.environ.get(f"NOTE_PASSWORD_{account_id}")
    if not email or not password:
        print(f"[SKIP] NOTE_EMAIL_{account_id} / NOTE_PASSWORD_{account_id} が未設定")
        return

    now   = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    state = load_state(account_id)

    print(f"\n{'='*55}")
    print(f"[note-auto] アカウント{account_id} {now.strftime('%Y-%m-%d %H:%M UTC')}")

    # ── Step1: リサーチ ──────────────────────────
    print("\n[1/3] テーマリサーチ中...")
    research = research_topic(account_id)
    research["account_id"] = account_id
    print(f"  ジャンル: {research['genre']}")
    print(f"  タイトル: {research['title']}")
    print(f"  価格:     ¥{research['price']}（{research['price_reason']}）")

    # ── Step2: 記事生成 ──────────────────────────
    print("\n[2/3] 記事生成中...")
    article = generate_article(research)
    print(f"  有料部分: {len(article['paid_body'])}字")

    backup = OUTPUT_DIR / f"{today}_auto_acct{account_id}.md"
    backup.write_text(
        f"# {article['title']}\n\n"
        f"<!-- 無料部分 -->\n{article['free_body']}\n\n"
        f"<!-- 有料部分 -->\n{article['paid_body']}\n",
        encoding="utf-8"
    )
    print(f"  バックアップ: {backup.name}")

    # ── Step3: 投稿 ──────────────────────────────
    print("\n[3/3] note.comに投稿中...")
    session_file = STATE_DIR / f"note_session_{account_id}.json"
    try:
        url = post_article(
            title        = article["title"],
            free_body    = article["free_body"],
            paid_body    = article["paid_body"],
            price        = research["price"],
            tags         = article.get("tags", research.get("keywords", [])),
            email        = email,
            password     = password,
            session_file = session_file,
        )
        print(f"  投稿完了: {url}")
        status = "success"
        # KDP連携フラグを立てる
        if research.get("kindle_book"):
            mark_book_note_linked(research["kindle_book"]["title"])
            print(f"  📚 KDP連携済み: {research['kindle_book']['title']}")
    except Exception as e:
        print(f"  [ERROR] {e}")
        status = "failed"
        url = None

    state["posted_topics"].append(research["topic"])
    state["articles"].append({
        "date": today, "title": article["title"],
        "price": research["price"], "url": url, "status": status,
    })
    save_state(account_id, state)
    print(f"[完了] アカウント{account_id}: {status.upper()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=int, choices=[1, 2, 3], default=None)
    args = parser.parse_args()

    if args.account:
        run(args.account)
    else:
        # 全アカウント順番に実行
        for acc_id in [1, 2, 3]:
            run(acc_id)
