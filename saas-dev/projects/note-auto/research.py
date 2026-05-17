"""
research.py — Geminiで今日投稿すべき「売れるテーマ」をリサーチ
"""
import os
import json
from pathlib import Path

try:
    from google import genai
except ImportError:
    print("pip install google-genai")
    exit(1)

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip()
                break

if not API_KEY:
    print("GEMINI_API_KEY が設定されていません")
    exit(1)

client = genai.Client(api_key=API_KEY)

GENRES = {
    1: {
        "name": "AI副業・ChatGPT活用系",
        "focus": "AI副業・ChatGPT活用・自動化・プロンプト術・AIツール活用で稼ぐ方法",
    },
    2: {
        "name": "お金・節約・投資入門系",
        "focus": "節約術・固定費削減・新NISA・積立投資・家計改善・ポイ活・副収入",
    },
    3: {
        "name": "就活・転職・キャリア系",
        "focus": "転職活動・面接対策・履歴書・職務経歴書・年収交渉・キャリア設計・副業",
    },
}

# KDPカテゴリ → noteアカウント対応表
KDP_CATEGORY_TO_ACCOUNT = {
    "副業・収入アップ": 1,
    "副業・スマホ": 1,
    "副業・Kindle出版": 1,
    "副業・物販": 1,
    "IT・AI活用": 1,
    "IT・スキルアップ": 1,
    "投資・資産形成": 2,
    "投資・シニア向け": 2,
    "節約・家計管理": 2,
    "節約・ふるさと納税": 2,
    "節約・一人暮らし": 2,
    "教育費・マネー": 2,
    "仕事術・生産性": 3,
    "メンタル・心理": 3,
}

BOOKS_JSON    = Path(__file__).parent.parent / "kindle-kdp" / "data" / "books.json"
STRATEGY_FILE = Path(__file__).parent / "pdca_strategy.json"


def load_account_strategy(account_id: int) -> dict:
    """pdca_strategy.json からアカウント別戦略を読み込む。なければ空。"""
    if not STRATEGY_FILE.exists():
        return {}
    try:
        data = json.loads(STRATEGY_FILE.read_text(encoding="utf-8"))
        return data.get("account_strategy", {}).get(str(account_id), {})
    except Exception:
        return {}


def find_unlinked_kindle_book(account_id: int) -> dict | None:
    """このアカウントのジャンルに対応する未連携KDP本を返す"""
    if not BOOKS_JSON.exists():
        return None
    books = json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    for book in reversed(books):  # 新しい本を優先
        if book.get("status") != "published":
            continue
        if book.get("note_linked"):
            continue
        if KDP_CATEGORY_TO_ACCOUNT.get(book.get("category", "")) == account_id:
            return book
    return None


def mark_book_note_linked(book_title: str):
    """KDP本にnote連携済みフラグを立てる"""
    if not BOOKS_JSON.exists():
        return
    books = json.loads(BOOKS_JSON.read_text(encoding="utf-8"))
    for book in books:
        if book.get("title") == book_title and not book.get("note_linked"):
            book["note_linked"] = True
            break
    BOOKS_JSON.write_text(json.dumps(books, ensure_ascii=False, indent=2), encoding="utf-8")


def load_posted_topics(account_id: int) -> list:
    state_file = Path(__file__).parent / f"state_{account_id}.json"
    if state_file.exists():
        return json.loads(state_file.read_text(encoding="utf-8")).get("posted_topics", [])
    return []


def research_topic(account_id: int) -> dict:
    genre    = GENRES[account_id]
    posted   = load_posted_topics(account_id)
    avoid    = "、".join(posted[-20:]) if posted else "なし"
    strategy = load_account_strategy(account_id)

    # PDCA戦略ヒントを構築
    pdca_hint = ""
    if strategy:
        focus      = strategy.get("focus", "")
        next_topics = strategy.get("next_topics", [])
        rec_price  = strategy.get("recommended_price", "")
        title_hook = strategy.get("title_hook", "")
        pdca_hint  = f"""
## PDCA戦略（優先的に従うこと）
- 今週の重点方向性: {focus}
- 推奨テーマ候補（この中から選ぶか、この方向性で新テーマを発掘）: {', '.join(next_topics)}
- 推奨価格: ¥{rec_price}
- 今週のタイトルパターン: {title_hook}
"""

    # アカウント1専用: 売れた記事パターンを明示
    sold_example_hint = ""
    if account_id == 1:
        sold_example_hint = """
## 実際に売れた記事の例（このパターンを参考にすること）
タイトル: 「Googleスプレッドシート×ChatGPT連携で100記事を一気に生成！コピペすら不要な「超」自動化ワークフロー」
価格: ¥500
なぜ売れたか: 「具体ツール×具体ツール」の組み合わせ、「コピペ不要」という強い約束、数字（100記事）で結果が見えた

## アカウント1のタイトル必勝パターン（必ずこれに近い形にすること）
パターン: 【具体的ツール名】×【具体的ツール名】で【具体的な成果・数字】！【強いサブタイトル】
例:
- 「Notion×Claude APIで週次レポートを完全自動化！1分もかからない「神ワークフロー」全公開」
- 「GASとChatGPTを繋いだら作業が10分→0分に！コピペだけで動く自動化スクリプト」
- 「Zapier×GPT-4oで問い合わせ対応を24時間完全自動化した手順を全部書く」
- 「スプレッドシート×Geminiで月100本のSNS投稿を一括生成する方法（テンプレ付き）」

## 避けるべきタイトル（曖昧・売れない）
- 「ChatGPTを使って副業で稼ぐ方法」（ツール名が1つ・成果が曖昧）
- 「AI副業で月10万円」（具体的な手順がない・誇大）
- 「プロンプト術まとめ」（まとめ系は安い）
"""

    prompt = f"""
あなたはnoteで月30万円以上稼いでいるライターのマネージャーです。
今日noteに投稿すべき「売れるテーマ」を1つ選んでください。

## ジャンル（このジャンル内で選ぶこと）
{genre['focus']}
{pdca_hint}{sold_example_hint}
## 条件
- 有料記事として売れる具体的なハウツー
- 読んだ人が「今すぐ再現できる」と感じる内容（手順が明確）
- noteで検索されやすいキーワードを含む
- タイトルに具体的なツール名・数字・結果を含める

## 価格判断基準（アカウント1は¥500を基本とする）
- ¥300: ちょっとしたTips・5分で読める（なるべく避ける）
- ¥500: 実践的ガイド・手順明確・再現性あり（推奨）
- ¥980: 完全マニュアル・これ1本で完結・テンプレ付き（複雑な自動化なら）

## 最近投稿済み（重複回避・必ずこれと被らないこと）
{avoid}

## 出力形式（JSONのみ・余分なテキスト不要）
{{
  "topic": "テーマ名（短く）",
  "title": "記事タイトル（具体的なツール名×ツール名・数字・結果を含める）",
  "target": "ターゲット読者（1行）",
  "angle": "差別化ポイント・切り口（1行）",
  "price": 500,
  "price_reason": "この価格にした理由（1行）",
  "keywords": ["キーワード1", "キーワード2", "キーワード3"]
}}
"""
    import time
    for attempt in range(5):
        try:
            response = client.models.generate_content(model="gemini-flash-latest", contents=prompt)
            break
        except Exception as e:
            err = str(e)
            if attempt < 4 and ("429" in err or "503" in err or "UNAVAILABLE" in err or "RESOURCE_EXHAUSTED" in err):
                wait = 60 * (attempt + 1)
                print(f"  [WAIT] APIエラー。{wait}秒後にリトライ({attempt+1}/4)...")
                time.sleep(wait)
            else:
                raise
    text = response.text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    result = json.loads(text)
    result["genre"] = genre["name"]

    # KDP連携: 未連携の関連Kindle本があれば追加
    kindle_book = find_unlinked_kindle_book(account_id)
    if kindle_book:
        result["kindle_book"] = {
            "title": kindle_book["title"],
            "description": kindle_book.get("description", ""),
        }
        print(f"  📚 KDP連携対象: {kindle_book['title']}")

    return result


if __name__ == "__main__":
    import sys
    acc = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print(json.dumps(research_topic(acc), ensure_ascii=False, indent=2))
