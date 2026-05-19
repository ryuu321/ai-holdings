"""
7日後フォローアップメール送信スクリプト
sent_log.csv の送信済みリストから N 日以上前に送った未フォロー先に sequence_2.txt を送る。

実行:
  python follow_up.py --dry-run     # 対象確認のみ（送信しない）
  python follow_up.py               # 実送信（7日以上前送信・未フォロー）
  python follow_up.py --days 3      # 指定日数以降を対象に（テスト用）
"""
import argparse
import csv
import io
import json
import os
import smtplib
import sys
import time
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass  # pytest / non-reconfigurable stdout

_DIR = Path(__file__).parent
_GTM_DIR = _DIR.parent.parent.parent.parent / "shared" / "gtm"
_CFG_FILE = _GTM_DIR / "config" / "fudotext.json"
_TEMPLATE_FILE = _GTM_DIR / "outreach" / "templates" / "sequence_2.txt"
SENT_LOG = _DIR / "sent_log.csv"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_DIR.parent.parent.parent.parent / ".env")
except ImportError:
    pass

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
SEND_INTERVAL = 30


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


def _get_followup_targets(log: list, days: int) -> list:
    """sent_log のリストから N日以上前に送った未フォロー対象を返す（テスト可能な純粋関数）"""
    cutoff = datetime.now() - timedelta(days=days)
    exclude = {row["email"] for row in log
               if row.get("result") in ("followup", "replied", "followup_failed")}
    targets = []
    seen = set()
    for row in log:
        if row.get("result") != "sent":
            continue
        email = row["email"]
        if email in seen or email in exclude:
            continue
        seen.add(email)
        try:
            sent_at = datetime.strptime(row["sent_at"][:16], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if sent_at <= cutoff:
            targets.append(row)
    return targets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=7, help="何日以上前の送信を対象にするか")
    args = parser.parse_args()

    with open(_CFG_FILE, encoding="utf-8") as f:
        cfg = json.load(f)
    template = _TEMPLATE_FILE.read_text(encoding="utf-8")

    if not SENT_LOG.exists():
        print("sent_log.csv が見つかりません。")
        return

    with open(SENT_LOG, encoding="utf-8") as f:
        log = list(csv.DictReader(f))

    targets = _get_followup_targets(log, args.days)

    print(f"フォローアップ対象: {len(targets)}件")
    print(f"  条件: {args.days}日以上前に送信済み / 未フォローアップ / 未返信")

    if not targets:
        today = datetime.now().strftime("%Y-%m-%d")
        first_sent = min(
            (row["sent_at"][:10] for row in log if row.get("result") == "sent"),
            default="不明"
        )
        due_date_str = ""
        try:
            first_dt = datetime.strptime(first_sent, "%Y-%m-%d")
            due = first_dt + timedelta(days=args.days)
            due_date_str = f"（次回フォローアップ予定: {due.strftime('%Y-%m-%d')}）"
        except Exception:
            pass
        print(f"対象なし。まだ {args.days} 日経過していない可能性があります。{due_date_str}")
        return

    for t in targets:
        print(f"  {t['company_name'][:35]} | {t['email']} | 送信日: {t['sent_at'][:10]}")

    if args.dry_run:
        print(f"\n（--dry-run: 実際には送信しません）")
        return

    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です。.env を確認してください。")
        return

    with open(SENT_LOG, "a", newline="", encoding="utf-8") as log_f:
        writer = csv.DictWriter(log_f,
                                fieldnames=["company_name", "email", "subject", "sent_at", "result"])
        for i, t in enumerate(targets, 1):
            company = t["company_name"]
            email = t["email"]
            body = template.format(
                company_name=company,
                sender_name=cfg["sender_name"],
                product_name=cfg["product_name"],
                app_url=cfg["app_url"],
                sender_email=cfg["sender_email"],
            )
            subject = f"Re: {t['subject']}"
            print(f"  [{i}/{len(targets)}] {company[:30]} <{email}>", end=" ... ")

            ok = _send(email, subject, body)
            result = "followup" if ok else "followup_failed"
            print("送信成功" if ok else "送信失敗")

            writer.writerow({
                "company_name": company,
                "email": email,
                "subject": subject,
                "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "result": result,
            })
            log_f.flush()

            if i < len(targets):
                time.sleep(SEND_INTERVAL)

    print(f"\nフォローアップ完了。")
    print(f"次のフォローアップは {args.days} 日後を目安に再実行してください。")


if __name__ == "__main__":
    main()
