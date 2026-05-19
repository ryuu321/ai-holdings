"""
ファネルKPIをターミナルに出力する

  python metrics.py --project fudotext
"""
import argparse
import csv
import io
import sys
from pathlib import Path

# Windows PowerShell でも日本語を表示する
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_GTM_DIR = Path(__file__).parent.parent


def load_csv_safe(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def metrics(project: str) -> None:
    data_dir = _GTM_DIR / "data" / project

    approved = load_csv_safe(data_dir / "leads_approved.csv")
    review = load_csv_safe(data_dir / "leads_review.csv")
    rejected = load_csv_safe(data_dir / "leads_rejected.csv")
    drafts = load_csv_safe(data_dir / "emails_draft.csv")
    sent_log = load_csv_safe(data_dir / "sent_log.csv")
    funnel = load_csv_safe(data_dir / "funnel.csv")

    # sent_log が fudotext プロジェクトの場合は outreach/ 直下を参照
    if not sent_log:
        fudotext_log = Path(__file__).parent.parent.parent.parent / "saas-dev/projects/fudosan-copy/outreach/sent_log.csv"
        if fudotext_log.exists():
            sent_log = load_csv_safe(fudotext_log)

    total_leads = len(approved) + len(review) + len(rejected)
    total_sent = sum(1 for r in sent_log if r.get("result") == "sent")
    total_failed = sum(1 for r in sent_log if r.get("result") == "failed")
    draft_count = sum(1 for d in drafts if d.get("status") == "draft") if drafts else 0

    # ファネル集計
    funnel_stages = {}
    if funnel:
        for row in funnel:
            stage = row.get("stage", "unknown")
            funnel_stages[stage] = funnel_stages.get(stage, 0) + 1

    sep = "=" * 50
    print(f"\n{sep}")
    print(f" GTM metrics: {project}")
    print(sep)
    print(f"\n[Lead Collection]")
    print(f"  Approved (80+): {len(approved):3}")
    print(f"  Review (60-79): {len(review):3}")
    print(f"  Rejected (<60): {len(rejected):3}")
    print(f"  Total:          {total_leads:3}")

    print(f"\n[Outreach]")
    print(f"  Sent:     {total_sent:3}")
    print(f"  Failed:   {total_failed:3}")
    print(f"  Draft:    {draft_count:3}")

    if total_sent > 0:
        replied = funnel_stages.get("replied", 0)
        demo = funnel_stages.get("demo", 0)
        closed = funnel_stages.get("closed", 0)
        reply_rate = replied / total_sent * 100 if total_sent else 0
        close_rate = closed / replied * 100 if replied else 0

        print(f"\n[Funnel]")
        print(f"  Replied:  {replied:3}  (reply rate {reply_rate:.1f}%)")
        print(f"  Demo:     {demo:3}")
        print(f"  Closed:   {closed:3}  (close rate {close_rate:.1f}% vs replied)")

        if funnel_stages:
            print(f"\n  Stages: {dict(funnel_stages)}")

    print(f"\n{sep}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    metrics(args.project)
