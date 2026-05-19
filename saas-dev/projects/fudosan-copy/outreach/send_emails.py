"""
Gmail SMTP で自動送信（100件/日）
入力: emails_draft.csv (status=draft のもの)
出力: sent_log.csv + emails_draft.csv の status を sent に更新

事前準備:
  1. Googleアカウント → セキュリティ → 2段階認証 ON
  2. アプリパスワード生成（16文字）
  3. 環境変数に設定:
     GMAIL_ADDRESS=ryuumg03@gmail.com
     GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

実行:
  python send_emails.py
  python send_emails.py --limit 50   # 50件だけ送る
"""
import argparse
import csv
import os
import smtplib
import time
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

_DIR = Path(__file__).parent
DRAFT_FILE = _DIR / "emails_draft.csv"
SENT_LOG = _DIR / "sent_log.csv"

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

DAILY_LIMIT = 100
SEND_INTERVAL = 30  # 秒（スパム判定回避）


def _send(to: str, subject: str, body: str) -> bool:
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"    送信失敗: {e}")
        return False


def _load_sent() -> set[str]:
    if not SENT_LOG.exists():
        return set()
    with open(SENT_LOG, encoding="utf-8", newline="") as f:
        return {row["email"] for row in csv.DictReader(f)}


def _today_sent_count() -> int:
    if not SENT_LOG.exists():
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    with open(SENT_LOG, encoding="utf-8", newline="") as f:
        return sum(1 for row in csv.DictReader(f) if row.get("sent_at", "").startswith(today))


def main(limit: int = DAILY_LIMIT):
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("環境変数が未設定です:")
        print("  $env:GMAIL_ADDRESS='ryuumg03@gmail.com'")
        print("  $env:GMAIL_APP_PASSWORD='アプリパスワード'")
        return

    if not DRAFT_FILE.exists():
        print("emails_draft.csv が見つかりません。generate_emails.py を先に実行してください。")
        return

    already_sent = _load_sent()
    today_count = _today_sent_count()
    remaining = limit - today_count

    if remaining <= 0:
        print(f"本日の送信上限（{limit}件）に達しています。明日再実行してください。")
        return

    print(f"本日送信済み: {today_count}件 / 残り: {remaining}件")

    with open(DRAFT_FILE, encoding="utf-8", newline="") as f:
        drafts = list(csv.DictReader(f))

    targets = [d for d in drafts if d["status"] == "draft" and d["email"] not in already_sent]
    targets = targets[:remaining]
    print(f"送信対象: {len(targets)}件")

    if not targets:
        print("送信対象がありません。collect_leads.py → generate_emails.py を実行してください。")
        return

    write_header = not SENT_LOG.exists()
    sent_emails = set()

    with open(SENT_LOG, "a", newline="", encoding="utf-8") as log_f:
        log_writer = csv.DictWriter(log_f, fieldnames=["company_name", "email", "subject", "sent_at", "result"])
        if write_header:
            log_writer.writeheader()

        for i, draft in enumerate(targets, 1):
            email = draft["email"]
            print(f"  [{i}/{len(targets)}] {draft['company_name'][:30]} <{email}>", end=" ... ")

            ok = _send(email, draft["subject"], draft["body"])
            result = "sent" if ok else "failed"
            print(result)

            log_writer.writerow({
                "company_name": draft["company_name"],
                "email": email,
                "subject": draft["subject"],
                "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "result": result,
            })
            log_f.flush()

            if ok:
                sent_emails.add(email)

            if i < len(targets):
                time.sleep(SEND_INTERVAL)

    # emails_draft.csv の status を更新
    updated = []
    for row in drafts:
        if row["email"] in sent_emails:
            row["status"] = "sent"
        updated.append(row)

    with open(DRAFT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "email", "subject", "body", "url", "status"])
        writer.writeheader()
        writer.writerows(updated)

    success = sum(1 for e in sent_emails)
    print(f"\n完了。送信成功: {success}件")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DAILY_LIMIT)
    args = parser.parse_args()
    main(limit=args.limit)
