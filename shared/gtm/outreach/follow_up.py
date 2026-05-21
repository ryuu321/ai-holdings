"""
共通 フォローアップメール送信スクリプト。
sent_log.csv の送信済みリストから N 日以上前に送った未フォロー先に sequence_2 を送る。

Usage:
  python follow_up.py --project sharotext --dry-run
  python follow_up.py --project fudotext --days 7
"""
import argparse
import csv
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
        pass

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CFG_DIR = _ROOT / "shared" / "gtm" / "config"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")


def _load_config(project: str) -> dict:
    path = _CFG_DIR / f"{project}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


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


def get_followup_targets(log: list, days: int) -> list:
    """N日以上前に送った未フォロー対象を返す（テスト可能な純粋関数）"""
    cutoff = datetime.now() - timedelta(days=days)
    exclude = {
        row["email"]
        for row in log
        if row.get("result") in ("followup", "replied", "followup_failed")
    }
    targets = []
    seen: set = set()
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="製品名 (fudotext / sharotext など)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=None, help="何日以上前の送信を対象にするか")
    args = parser.parse_args()

    cfg = _load_config(args.project)
    days = args.days if args.days is not None else cfg.get("followup_days", 7)
    sent_log = _ROOT / cfg["sent_log"]
    template_path = _ROOT / cfg["followup_template"]
    send_interval = cfg.get("send_interval_sec", 30)

    template = template_path.read_text(encoding="utf-8")

    if not sent_log.exists():
        print("sent_log.csv が見つかりません。")
        return

    with open(sent_log, encoding="utf-8") as f:
        log = list(csv.DictReader(f))

    targets = get_followup_targets(log, days)
    product_name = cfg["product_name"]

    print(f"[{product_name}] フォローアップ対象: {len(targets)}件")
    print(f"  条件: {days}日以上前に送信済み / 未フォロー / 未返信")

    if not targets:
        first_sent = min(
            (row["sent_at"][:10] for row in log if row.get("result") == "sent"),
            default="不明",
        )
        try:
            due = datetime.strptime(first_sent, "%Y-%m-%d") + timedelta(days=days)
            print(f"対象なし。次回フォローアップ予定: {due.strftime('%Y-%m-%d')}")
        except Exception:
            print(f"対象なし。最初の送信日: {first_sent}")
        return

    for t in targets:
        print(f"  {t['company_name'][:35]} | {t['email']} | 送信日: {t['sent_at'][:10]}")

    if args.dry_run:
        print("\n（--dry-run: 実際には送信しません）")
        return

    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です。")
        return

    with open(sent_log, "a", newline="", encoding="utf-8") as log_f:
        writer = csv.DictWriter(
            log_f,
            fieldnames=["company_name", "email", "subject", "sent_at", "result"],
        )
        for i, t in enumerate(targets, 1):
            company = t["company_name"]
            email = t["email"]
            body = template.format(
                company_name=company,
                sender_name=cfg["sender_name"],
                product_name=cfg["product_name"],
                app_url=cfg["app_url"],
                sender_email=cfg["sender_email"],
                sender_address=cfg.get("sender_address", ""),
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
                time.sleep(send_interval)

    print(f"\nフォローアップ完了。次回は {days} 日後を目安に再実行してください。")


if __name__ == "__main__":
    main()
