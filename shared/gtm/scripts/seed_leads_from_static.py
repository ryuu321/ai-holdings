#!/usr/bin/env python3
"""
seed_leads_from_static.py — 静的リストからleads.csvを補充する

Brave API失敗時のフォールバック。leads_static.csvから未送信分をleads.csvに補充。

Usage（ワークフロー内）:
  python shared/gtm/scripts/seed_leads_from_static.py --project sharotext --limit 100
"""
import argparse
import csv
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent.parent.parent
PROJECTS_DIR = ROOT / "saas-dev" / "projects"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    proj_dir = PROJECTS_DIR / args.project / "outreach"
    static_path = proj_dir / "leads_static.csv"
    leads_path = proj_dir / "leads.csv"
    sent_path = proj_dir / "sent_log.csv"

    if not static_path.exists():
        print(f"leads_static.csv が見つかりません: {static_path}")
        print("generate_static_leads.py を先に実行してください")
        sys.exit(1)

    # 送信済みメールを収集
    sent_emails = set()
    if sent_path.exists():
        with open(sent_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                email = row.get("email", "").strip()
                if email:
                    sent_emails.add(email.lower())

    # 既存のleads.csvのメールも収集（重複防止）
    existing_emails = set()
    if leads_path.exists():
        with open(leads_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                email = row.get("email", "").strip()
                if email:
                    existing_emails.add(email.lower())

    skip_emails = sent_emails | existing_emails

    # 静的リストから未送信分を選択
    new_rows = []
    with open(static_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            email = row.get("email", "").strip()
            if email.lower() not in skip_emails:
                new_rows.append(row)
            if len(new_rows) >= args.limit:
                break

    if not new_rows:
        print(f"静的リストに未送信分がありません（全{len(sent_emails)}件送信済み）")
        return

    # leads.csvに追記（なければ新規作成）
    fieldnames = ["company_name", "email", "url", "prefecture", "scraped_at"]
    mode = "a" if leads_path.exists() else "w"
    with open(leads_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if mode == "w":
            writer.writeheader()
        writer.writerows(new_rows)

    print(f"静的リードから{len(new_rows)}件補充 → leads.csv")
    print(f"（送信済み除外: {len(sent_emails)}件 / 静的リスト総数: {sum(1 for _ in open(static_path, encoding='utf-8'))-1}件）")


if __name__ == "__main__":
    main()
