"""
日次レポート生成スクリプト（LLM不要・無料）
投資ボットの実績 + ナレッジベースの状態を表示する
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).parent.parent.parent / "saas-dev/projects/auto-invest/data/trades.db"
KNOWLEDGE_ROOT = Path(__file__).parent.parent / "knowledge"


def investment_report() -> str:
    lines = ["=== 投資ボット レポート ==="]
    if not DB_PATH.exists():
        lines.append("  DBなし（まだ取引なし）")
        return "\n".join(lines)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM trades WHERE action != 'HOLD'")
    total = cur.fetchone()[0]

    cur.execute("SELECT SUM(pnl) FROM trades WHERE action = 'SELL'")
    pnl = cur.fetchone()[0] or 0.0

    cur.execute("SELECT COUNT(*) FROM trades WHERE action='SELL' AND pnl > 0")
    wins = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM trades WHERE action='SELL'")
    sells = cur.fetchone()[0]

    cur.execute("SELECT action, price, pnl, timestamp FROM trades ORDER BY timestamp DESC LIMIT 3")
    recent = cur.fetchall()
    conn.close()

    win_rate = (wins / sells * 100) if sells > 0 else 0.0
    lines.append(f"  取引回数: {total}  勝率: {win_rate:.1f}%  累計損益: ${pnl:,.2f}")
    lines.append("  直近3件:")
    for r in recent:
        lines.append(f"    [{r[0]}] ${r[1]:,.0f}  PnL=${r[2]:,.2f}  {r[3][:16]}")
    return "\n".join(lines)


def knowledge_report() -> str:
    lines = ["=== ナレッジベース 状態 ==="]
    domains = {
        "love":     ["experiences.md", "philosophy.md"],
        "business": ["strategy.md"],
        "life":     ["thoughts.md"],
        "tech":     ["ideas.md"],
    }
    for domain, files in domains.items():
        for f in files:
            path = KNOWLEDGE_ROOT / domain / f
            if path.exists():
                content = path.read_text(encoding="utf-8")
                entries = [l for l in content.splitlines()
                           if l.strip() and not l.startswith("#") and not l.startswith("<!--")]
                lines.append(f"  {domain}/{f}: {len(entries)}行")
    return "\n".join(lines)


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*45}")
    print(f"  日次レポート  {now}")
    print(f"{'='*45}")
    print(investment_report())
    print()
    print(knowledge_report())
    print()


if __name__ == "__main__":
    main()
