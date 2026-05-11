#!/usr/bin/env python3
"""
AI Holdings — CEO オーケストレーター
使い方: python run.py "タスクの内容"
"""

import subprocess
import sys
import json
from pathlib import Path

BASE = Path(__file__).parent

COMPANIES = {
    "saas-dev":   "SaaS開発社",
    "note-biz":   "note副業社",
    "sns-ops":    "SNS運用社",
    "consulting": "コンサル社",
    "macro-biz":  "マクロBiz社",
}

def load_claude_md(company: str) -> str:
    path = BASE / company / "CLAUDE.md"
    return path.read_text(encoding="utf-8")

def load_context() -> dict:
    path = BASE / "shared" / "memory" / "context.json"
    return json.loads(path.read_text(encoding="utf-8"))

def ask_ceo(task: str) -> str:
    """ホールディングスCEOにタスクを渡して委任先を決めてもらう"""
    ceo_md = (BASE / "CLAUDE.md").read_text(encoding="utf-8")
    context = load_context()

    prompt = f"""あなたはAI Holdingsのホールディングスです。

{ceo_md}

## 現在の会社状況
{json.dumps(context["company_status"], ensure_ascii=False, indent=2)}

## ユーザーからのタスク
{task}

## 指示
1. このタスクをどの会社（複数可）が担当すべきか判断してください
2. 各社への具体的な指示内容を書いてください
3. 以下のJSON形式で回答してください:

{{
  "analysis": "タスクの分析",
  "assignments": [
    {{"company": "saas-dev", "instruction": "具体的な指示"}},
    {{"company": "note-biz", "instruction": "具体的な指示"}}
  ],
  "synergy": "会社間の連携ポイント（あれば）"
}}
"""

    result = subprocess.run(
        ["claude", "--print", "-p", ceo_md, prompt],
        capture_output=True, text=True
    )
    return result.stdout

def delegate_to_company(company: str, instruction: str) -> str:
    """各社の社長エージェントにタスクを委任"""
    company_md = load_claude_md(company)
    company_name = COMPANIES.get(company, company)

    print(f"\n📤 [{company_name}] に委任中...")

    result = subprocess.run(
        ["claude", "--print", "-p", company_md, instruction],
        capture_output=True, text=True
    )
    return result.stdout

def main():
    if len(sys.argv) < 2:
        print("使い方: python run.py 'タスクの内容'")
        sys.exit(1)

    task = " ".join(sys.argv[1:])
    print(f"🏢 AI Holdings CEO — タスク受付: {task}\n")
    print("=" * 60)

    # CEOが委任先を決定
    print("🤔 CEO が担当会社を判断中...")
    ceo_response = ask_ceo(task)
    print(f"\nCEO判断:\n{ceo_response}\n")
    print("=" * 60)

    # JSONを抽出して各社に委任
    try:
        import re
        json_match = re.search(r'\{.*\}', ceo_response, re.DOTALL)
        if json_match:
            plan = json.loads(json_match.group())
            results = {}
            for assignment in plan.get("assignments", []):
                company = assignment["company"]
                instruction = assignment["instruction"]
                result = delegate_to_company(company, instruction)
                results[company] = result
                print(f"\n✅ [{COMPANIES.get(company, company)}] 完了:\n{result[:500]}...")

            print("\n" + "=" * 60)
            print("📊 CEO統合レポート")
            print("=" * 60)
            print(f"シナジー: {plan.get('synergy', 'なし')}")
            print(f"完了会社: {list(results.keys())}")
    except Exception as e:
        print(f"⚠️  JSON解析エラー: {e}")
        print("CEOの判断結果を直接参照してください")

if __name__ == "__main__":
    main()
