"""
Kindle KDP EPUB自動生成
実行: python main.py

週1回 GitHub Actions で実行。
1回につき1冊生成→EPUBに変換→outputフォルダに保存。
KDPへのアップロードは手動（週10分）。
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from groq import Groq
from settings import settings
from generator import generate_book, pick_next_topic
from epub_builder import build_epub

DATA_FILE = Path(__file__).parent / "data" / "books.json"
OUTPUT_DIR = Path(__file__).parent / "output"


def load_books() -> list:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return []


def save_books(books: list):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(books, ensure_ascii=False, indent=2), encoding="utf-8")


def run():
    now = datetime.now(timezone.utc)
    print(f"\n{'='*55}")
    print(f"[kindle-kdp] {now.strftime('%Y-%m-%d %H:%M UTC')}")

    books = load_books()
    done_topics = [b["topic"] for b in books if b.get("status") in ("epub_ready", "published")]

    topic_data = pick_next_topic(done_topics)
    if not topic_data:
        print("全トピック生成済みです。")
        return

    topic, category, keywords = topic_data
    print(f"トピック: {topic} ({category})")

    client = Groq(api_key=settings.GROQ_API_KEY)

    print("  [1/2] コンテンツ生成中（Groq）...")
    book_data = generate_book(topic, category, client)
    book_data["keywords"] = keywords
    print(f"  タイトル: {book_data['title']}")

    print("  [2/2] EPUB作成中...")
    book_output_dir = OUTPUT_DIR / f"{len(books)+1:03d}_{topic[:20]}"
    epub_path = build_epub(book_data, book_output_dir)

    books.append({
        "topic":        topic,
        "title":        book_data["title"],
        "subtitle":     book_data.get("subtitle", ""),
        "author":       book_data.get("author", ""),
        "description":  book_data.get("description", ""),
        "keywords":     keywords,
        "category":     category,
        "epub_path":    str(epub_path),
        "status":       "epub_ready",
        "generated_at": now.isoformat(),
    })
    save_books(books)

    print(f"\n{'='*55}")
    print(f"[完了] EPUBを生成しました: {epub_path}")
    print(f"→ KDPにアップロードしてください")
    print(f"累計生成: {len(books)}冊")


if __name__ == "__main__":
    run()
