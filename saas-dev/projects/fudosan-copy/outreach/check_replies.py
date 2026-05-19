"""
Gmail IMAP で返信を確認する
sent_log.csv の送信先からの受信メールを検索してレポート

実行:
  python check_replies.py           # 全送信先の返信を確認
  python check_replies.py --mark    # replied 状態を sent_log.csv に記録する
"""
import argparse
import csv
import email as email_lib
import imaplib
import io
import os
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass  # pytest / non-reconfigurable stdout

_DIR = Path(__file__).parent
SENT_LOG = _DIR / "sent_log.csv"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_DIR.parent.parent.parent.parent / ".env")
except ImportError:
    pass

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993


def get_sent_addresses() -> dict[str, str]:
    """sent_log.csv から {email: company_name} を返す"""
    if not SENT_LOG.exists():
        return {}
    with open(SENT_LOG, encoding="utf-8") as f:
        return {row["email"]: row["company_name"] for row in csv.DictReader(f)
                if row.get("result") == "sent"}


def check_replies(sent_addrs: dict[str, str]) -> list[dict]:
    """IMAP で受信箱を検索して返信を探す"""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です。")
        return []

    replies = []
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("INBOX")

        for addr, company in sent_addrs.items():
            _, data = mail.search(None, f'FROM "{addr}"')
            msg_ids = data[0].split()
            if not msg_ids:
                continue

            for msg_id in msg_ids[-3:]:  # 最新3件のみ確認
                _, msg_data = mail.fetch(msg_id, "(RFC822)")
                raw = msg_data[0][1]
                msg = email_lib.message_from_bytes(raw)
                subject = email_lib.header.decode_header(msg["Subject"] or "")[0]
                subject_str = subject[0].decode(subject[1] or "utf-8", errors="ignore") \
                    if isinstance(subject[0], bytes) else subject[0]
                date_str = msg.get("Date", "")

                replies.append({
                    "company": company,
                    "from": addr,
                    "subject": subject_str,
                    "date": date_str[:25],
                })

        mail.logout()
    except Exception as e:
        print(f"IMAP接続エラー: {e}")

    return replies


def mark_replied(replied_emails: set[str]) -> None:
    """sent_log.csv の該当エントリを replied に更新"""
    if not SENT_LOG.exists():
        return
    with open(SENT_LOG, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fields = list(rows[0].keys()) if rows else []
    updated = []
    for row in rows:
        if row["email"] in replied_emails and row["result"] == "sent":
            row["result"] = "replied"
        updated.append(row)

    with open(SENT_LOG, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(updated)
    print(f"{len(replied_emails)}件を replied に更新しました。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mark", action="store_true", help="返信済みを sent_log.csv に記録")
    args = parser.parse_args()

    sent_addrs = get_sent_addresses()
    print(f"送信先 {len(sent_addrs)}社 を確認中...")

    replies = check_replies(sent_addrs)

    print(f"\n{'='*55}")
    print(f"返信状況レポート ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print(f"{'='*55}")

    if not replies:
        print("返信なし（受信箱に対象メールアドレスからのメールが見つかりません）")
    else:
        print(f"返信あり: {len(replies)}件")
        for r in replies:
            print(f"\n  会社: {r['company'][:40]}")
            print(f"  From: {r['from']}")
            print(f"  件名: {r['subject'][:60]}")
            print(f"  日時: {r['date']}")

    print(f"\n{'='*55}")
    print("【対応方針】")
    if replies:
        print("返信あり → 内容を確認してコード発行:")
        print("  python gen_access_code.py --company \"会社名\" --plan standard --to email@example.com")
    else:
        print("返信なし → 2026-05-26にフォローアップメールを予定 (follow_up.py)")

    if args.mark and replies:
        replied_set = {r["from"] for r in replies}
        mark_replied(replied_set)


if __name__ == "__main__":
    main()
