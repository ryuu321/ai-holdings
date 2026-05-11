#!/usr/bin/env python3
"""
shared/tools/logger.py
エージェント実行ログの記録・参照ツール
"""

import json
import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_FILE = LOG_DIR / "executions.jsonl"

def log_execution(company: str, agent: str, task: str, result: str, tokens_est: int = 0):
    """エージェント実行をログに記録"""
    LOG_DIR.mkdir(exist_ok=True)
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "company": company,
        "agent": agent,
        "task_preview": task[:100],
        "result_preview": result[:200],
        "tokens_estimated": tokens_est,
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def show_recent(n: int = 10):
    """直近N件のログを表示"""
    if not LOG_FILE.exists():
        print("ログがまだありません")
        return
    lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
    for line in lines[-n:]:
        entry = json.loads(line)
        print(f"[{entry['timestamp'][:16]}] {entry['company']}/{entry['agent']}")
        print(f"  タスク: {entry['task_preview']}")
        print(f"  結果: {entry['result_preview'][:80]}...")
        print()

def monthly_summary():
    """今月の実行サマリー"""
    if not LOG_FILE.exists():
        return {}
    this_month = datetime.datetime.now().strftime("%Y-%m")
    counts = {}
    lines = LOG_FILE.read_text(encoding="utf-8").strip().split("\n")
    for line in lines:
        entry = json.loads(line)
        if entry["timestamp"].startswith(this_month):
            key = entry["company"]
            counts[key] = counts.get(key, 0) + 1
    return counts

if __name__ == "__main__":
    show_recent(5)
    print("今月の実行数:", monthly_summary())
