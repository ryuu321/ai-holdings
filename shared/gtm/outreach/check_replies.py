"""
共通 返信確認スクリプト。各製品の sent_log.csv を IMAP で検索し Telegram 通知。

Usage:
  python check_replies.py --project fudotext
  python check_replies.py --project sharotext --mark
"""
import argparse
import csv
import email as email_lib
import imaplib
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
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


def _load_config(project: str) -> dict:
    path = _CFG_DIR / f"{project}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _notify_telegram(product_name: str, replies: list) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHANNEL_ID", "")
    if not token or not chat_id:
        return
    lines = [f"\U0001f4e9 {product_name} 返信あり: {len(replies)}件"]
    for r in replies:
        lines.append(f"\n会社: {r['company'][:30]}")
        lines.append(f"From: {r['from']}")
        lines.append(f"件名: {r['subject'][:40]}")
    lines.append("\n→ アクセスコードを発行してください")
    text = "\n".join(lines)
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception as e:
        print(f"Telegram通知失敗: {e}")


def get_sent_addresses(sent_log: Path) -> dict[str, str]:
    if not sent_log.exists():
        return {}
    with open(sent_log, encoding="utf-8") as f:
        return {
            row["email"]: row["company_name"]
            for row in csv.DictReader(f)
            if row.get("result") == "sent"
        }


def check_replies(sent_addrs: dict[str, str]) -> list[dict]:
    gmail = os.environ.get("GMAIL_ADDRESS", "")
    pwd = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not gmail or not pwd:
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です。")
        return []

    replies = []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(gmail, pwd)
        mail.select("INBOX")
        for addr, company in sent_addrs.items():
            _, data = mail.search(None, f'FROM "{addr}"')
            msg_ids = data[0].split()
            if not msg_ids:
                continue
            for msg_id in msg_ids[-3:]:
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
                subject = email_lib.header.decode_header(msg["Subject"] or "")[0]
                subject_str = (
                    subject[0].decode(subject[1] or "utf-8", errors="ignore")
                    if isinstance(subject[0], bytes)
                    else subject[0]
                )
                replies.append({
                    "company": company,
                    "from": addr,
                    "subject": subject_str,
                    "date": msg.get("Date", "")[:25],
                })
        mail.logout()
    except Exception as e:
        print(f"IMAP接続エラー: {e}")

    return replies


def mark_replied(sent_log: Path, replied_emails: set) -> None:
    if not sent_log.exists():
        return
    with open(sent_log, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return
    fields = list(rows[0].keys())
    for row in rows:
        if row["email"] in replied_emails and row.get("result") == "sent":
            row["result"] = "replied"
    with open(sent_log, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(replied_emails)}件を replied に更新しました。")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="製品名 (fudotext / sharotext / kentext など)")
    parser.add_argument("--mark", action="store_true", help="返信済みを sent_log.csv に記録")
    args = parser.parse_args()

    cfg = _load_config(args.project)
    product_name = cfg["product_name"]
    sent_log = _ROOT / cfg["sent_log"]

    sent_addrs = get_sent_addresses(sent_log)
    print(f"[{product_name}] 送信先 {len(sent_addrs)}社 を確認中...")

    replies = check_replies(sent_addrs)

    print(f"\n{'='*55}")
    print(f"{product_name} 返信状況レポート ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"{'='*55}")

    if not replies:
        print("返信なし")
    else:
        print(f"返信あり: {len(replies)}件")
        for r in replies:
            print(f"\n  会社: {r['company'][:40]}")
            print(f"  From: {r['from']}")
            print(f"  件名: {r['subject'][:60]}")
            print(f"  日時: {r['date']}")
        _notify_telegram(product_name, replies)
        print("\n→ アクセスコードを発行して GitHub Actions send-code を実行してください。")

    if args.mark and replies:
        mark_replied(sent_log, {r["from"] for r in replies})


if __name__ == "__main__":
    main()
