"""
research_daily.py — Gemini による毎日の情報収集 + CEOスコアリング

実行: python shared/tools/research_daily.py
出力: research/output/YYYY-MM-DD_report.md
      research/output/YYYY-MM-DD_opportunity.md（チャンス検出時のみ）
"""

import os
import json
from datetime import datetime
from pathlib import Path

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("google-genai が未インストールです。pip install google-genai を実行してください。")
    exit(1)

# --- 設定 ---
API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    # .env から読み込み
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip()
                break

if not API_KEY:
    print("GEMINI_API_KEY が設定されていません。")
    exit(1)

client = genai.Client(api_key=API_KEY)

TODAY = datetime.now().strftime("%Y-%m-%d")
OUTPUT_DIR = Path(__file__).parent.parent.parent / "research" / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# --- 調査テーマ ---
TOPICS = [
    {
        "id": "ai_tools",
        "name": "AIツール・エージェントの最新動向",
        "query": "2024年〜2025年の最新AIツール・AIエージェントサービスで注目されているもの、新しいリリース、トレンドを日本語で教えてください。具体的なサービス名と特徴を含めてください。",
    },
    {
        "id": "note_market",
        "name": "noteコンテンツ市場のトレンド",
        "query": "noteで売れている有料記事・マガジンのジャンルや傾向、恋愛・自己啓発系コンテンツの需要について日本語で教えてください。",
    },
    {
        "id": "salon_instagram",
        "name": "個人サロンInstagram運用の最新情報",
        "query": "個人サロン（ネイル・まつ毛・エステ・整体など）のInstagram運用で伸びているアカウントの特徴、最新のアルゴリズム変化、運用代行の市場について日本語で教えてください。",
    },
    {
        "id": "ai_side_business",
        "name": "AI副業・新しい副業情報",
        "query": "AIを活用した副業、楽天Roomなどのアフィリエイト副業、2024〜2025年に注目されている新しい副業手法について日本語で教えてください。初期費用ゼロ・無料で始められるものを優先して教えてください。",
    },
    {
        "id": "macro_economy",
        "name": "投資・経済マクロの最新動向",
        "query": "現在の経済フェーズ、株式市場のトレンド、地政学リスク、注目されている投資戦略について日本語で簡潔に教えてください。",
    },
]

# --- CEOスコアリング基準 ---
SCORING_PROMPT = """
あなたはAI Holdingsのスコアリングエージェントです。
以下のリサーチ結果を読んで、新規事業機会を検出してください。

## 評価基準（各10点満点）
1. 初期費用ゼロで始められるか（必須条件：0円以外はスコア0）
2. 3ヶ月以内に収益化できるか
3. 1日1時間以内で運用できるか
4. 既存事業（note-biz/sns-ops/consulting/saas-dev）との親和性

## 既存事業
- note-biz: 恋愛・自己肯定感コンテンツのnoteマガジン
- sns-ops: 個人サロン向けInstagram運用代行
- consulting: 音声相談サービス（保留中）
- saas-dev: 投資ボット・自動化ツール開発

## 出力形式（JSON）
{
  "opportunities": [
    {
      "title": "機会のタイトル",
      "description": "1〜2行の説明",
      "score": 0〜40の合計スコア,
      "assign_to": "既存事業に振り分ける場合は会社名、新規の場合は'new'",
      "new_company_name": "新規の場合の事業部名（assignがnewの時のみ）",
      "reason": "CEOとしての判断理由"
    }
  ]
}

スコアが25以上のものだけ含めてください。
リサーチ結果:
"""


def fetch_topic(topic: dict) -> str:
    """Gemini でトピックを調査する"""
    try:
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=topic["query"]
        )
        return response.text
    except Exception as e:
        return f"取得エラー: {e}"


def score_opportunities(research_summary: str) -> list:
    """CEOロジックでスコアリング"""
    try:
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=SCORING_PROMPT + research_summary
        )
        text = response.text.strip()
        # JSONブロックを抽出
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        data = json.loads(text)
        return data.get("opportunities", [])
    except Exception as e:
        print(f"スコアリングエラー: {e}")
        return []


def main():
    print(f"=== research_daily.py 実行 {TODAY} ===")

    # --- 各トピックを調査 ---
    results = {}
    for topic in TOPICS:
        print(f"調査中: {topic['name']} ...")
        results[topic["id"]] = {
            "name": topic["name"],
            "content": fetch_topic(topic),
        }

    # --- レポート生成 ---
    report_lines = [
        f"# リサーチレポート — {TODAY}\n",
        f"生成: Gemini 1.5 Flash\n",
        "---\n",
    ]
    summary_text = ""
    for topic_id, result in results.items():
        report_lines.append(f"## {result['name']}\n")
        report_lines.append(result["content"] + "\n")
        report_lines.append("---\n")
        summary_text += f"【{result['name']}】\n{result['content']}\n\n"

    report_path = OUTPUT_DIR / f"{TODAY}_report.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"レポート保存: {report_path}")

    # --- CEOスコアリング ---
    print("CEOスコアリング中...")
    opportunities = score_opportunities(summary_text)

    if opportunities:
        opp_lines = [
            f"# 新規事業機会レポート — {TODAY}\n",
            "CEOスコアリングにより検出された機会です。次のClaudeセッションで確認・判断してください。\n",
            "---\n",
        ]
        for opp in opportunities:
            opp_lines.append(f"## {opp.get('title', '無題')}  （スコア: {opp.get('score', 0)}/40）\n")
            opp_lines.append(f"**概要**: {opp.get('description', '')}\n")
            assign = opp.get("assign_to", "")
            if assign == "new":
                opp_lines.append(f"**判断**: 新規事業部 `{opp.get('new_company_name', '')}` を作成推奨\n")
            else:
                opp_lines.append(f"**判断**: 既存事業 `{assign}` に振り分け推奨\n")
            opp_lines.append(f"**理由**: {opp.get('reason', '')}\n")
            opp_lines.append("---\n")

        opp_path = OUTPUT_DIR / f"{TODAY}_opportunity.md"
        opp_path.write_text("\n".join(opp_lines), encoding="utf-8")
        print(f"機会レポート保存: {opp_path}  ({len(opportunities)}件検出)")

        # ventures.md への追記はCEOが /ventures でレビュー後に手動判断する
    else:
        print("新規事業機会: 検出なし（スコア25未満）")

    print("=== 完了 ===")


if __name__ == "__main__":
    main()
