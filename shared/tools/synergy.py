#!/usr/bin/env python3
"""
shared/tools/synergy.py
会社間シナジーを実行するためのヘルパーツール
"""

import subprocess
import json
from pathlib import Path

BASE = Path(__file__).parent.parent.parent  # ai-holdings/

def run_agent(company: str, agent_dir: str, task: str) -> str:
    """特定の会社・エージェントにタスクを実行させる"""
    claude_md_path = BASE / company / agent_dir / "CLAUDE.md"
    if not claude_md_path.exists():
        claude_md_path = BASE / company / "CLAUDE.md"

    system_prompt = claude_md_path.read_text(encoding="utf-8")
    result = subprocess.run(
        ["claude", "--print", "-p", system_prompt, task],
        capture_output=True, text=True
    )
    return result.stdout.strip()

def synergy_note_to_sns(note_title: str, note_summary: str) -> dict:
    """note記事 → SNS告知の自動シナジー"""
    print("🔄 シナジー起動: note → SNS")

    post = run_agent("sns-ops", "post-gen",
        f"以下のnote記事の告知投稿を作成してください。\n記事タイトル: {note_title}\n概要: {note_summary}")

    return {"platform_posts": post}

def synergy_macro_to_all(trend_report: str) -> dict:
    """マクロ分析 → 全社への展開指示"""
    print("🔄 シナジー起動: マクロBiz → 全社展開")

    results = {}
    companies = [
        ("saas-dev", f"以下のトレンドをもとに、プロダクト方針への示唆を出してください。\n{trend_report}"),
        ("note-biz", f"以下のトレンドをもとに、記事テーマを3つ提案してください。\n{trend_report}"),
        ("sns-ops",  f"以下のトレンドをもとに、SNS投稿ネタを3つ提案してください。\n{trend_report}"),
        ("consulting", f"以下のトレンドをもとに、クライアントへの提案ポイントを出してください。\n{trend_report}"),
    ]

    for company, task in companies:
        print(f"  → {company} に展開中...")
        results[company] = run_agent(company, "", task)

    return results

def synergy_consulting_to_note(case_study: str) -> str:
    """コンサル事例 → note記事化"""
    print("🔄 シナジー起動: コンサル事例 → note記事")
    return run_agent("note-biz", "writer",
        f"以下のコンサル事例を魅力的なnote記事に変換してください。\n{case_study}")

def update_context(key: str, value) -> None:
    """shared/memory/context.jsonを更新"""
    ctx_path = BASE / "shared" / "memory" / "context.json"
    ctx = json.loads(ctx_path.read_text(encoding="utf-8"))

    keys = key.split(".")
    d = ctx
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value

    ctx_path.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ context更新: {key} = {value}")

if __name__ == "__main__":
    # 使用例
    result = synergy_note_to_sns(
        "Claude Codeで会社を作った話",
        "AIエージェントを5社に分けて階層管理する仕組みを構築した体験記"
    )
    print(result)
