"""
ナレッジベースから記事を自動生成するスクリプト
質問なし・APIキー不要版（Claude Codeが呼び出す想定）

使い方:
  python auto-article.py --domain love --theme "依存しない男"

引数:
  --domain   love / business / life / tech
  --theme    記事のテーマ（一言）
  --output   出力ファイルパス（省略時はstdout）
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

KNOWLEDGE_ROOT = Path(__file__).parent.parent.parent / "shared" / "knowledge"

DOMAIN_FILES = {
    "love": [
        "love/philosophy.md",
        "love/experiences.md",
    ],
    "business": [
        "business/strategy.md",
    ],
    "life": [
        "life/thoughts.md",
    ],
    "tech": [
        "tech/ideas.md",
    ],
}

ARTICLE_TEMPLATE = """
以下のナレッジベースの内容を元に、noteのマガジン記事を書いてください。

## テーマ
{theme}

## ナレッジベース（筆者の実体験・哲学・経験）
{knowledge}

## 記事の条件
- 文体: 「〜んですよね」「〜んです」「〜ですよ」調。説教くさくしない
- 文字数: 3,000字以上
- 構成:
  【無料部分・約300字】
  - 書き出し: 読者のあるある場面で共感を掴む
  - 「実はこれ、全部同じ原因から来てる」という問題提起
  - 答えを持っている暗示
  - 「続きでその全部を話します」で締める
  ↑ここで「続きを読む」ボタン↑
  【有料部分・約2,700字】
  - 問題の深掘り（具体的場面描写）
  - 解決策・考え方
  - 実践方法
  - 締め（読者への核心メッセージ）
  - 「次号に続く。」で終わる
- 重要な一文は**太字**
- ナレッジベースの実体験を具体的なエピソードとして使う
- タイトル形式: 「核心メッセージ。── サブタイトル」
"""


def load_knowledge(domain: str) -> str:
    files = DOMAIN_FILES.get(domain, [])
    content_parts = []
    for rel_path in files:
        full_path = KNOWLEDGE_ROOT / rel_path
        if full_path.exists():
            text = full_path.read_text(encoding="utf-8")
            # コメント行を除去
            lines = [l for l in text.splitlines() if not l.strip().startswith("<!--")]
            content_parts.append("\n".join(lines))
    return "\n\n---\n\n".join(content_parts)


def generate_prompt(theme: str, domain: str) -> str:
    knowledge = load_knowledge(domain)
    if not knowledge.strip():
        print(f"[!] ナレッジが空です: {domain}", file=sys.stderr)
        sys.exit(1)
    return ARTICLE_TEMPLATE.format(theme=theme, knowledge=knowledge)


def main():
    parser = argparse.ArgumentParser(description="ナレッジベースから記事プロンプトを生成")
    parser.add_argument("--domain", required=True, choices=["love", "business", "life", "tech"])
    parser.add_argument("--theme", required=True, help="記事のテーマ")
    parser.add_argument("--output", default=None, help="出力ファイルパス")
    args = parser.parse_args()

    prompt = generate_prompt(args.theme, args.domain)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(prompt, encoding="utf-8")
        print(f"[OK] プロンプト出力: {out_path}")
    else:
        print(prompt)


if __name__ == "__main__":
    main()
