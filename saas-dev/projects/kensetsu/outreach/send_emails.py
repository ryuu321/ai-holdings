"""
KenText アウトリーチ送信スクリプト（Gmail SMTP・30件/日）
入力: emails_draft.csv (status=draft)
出力: sent_log.csv + emails_draft.csv の status を sent に更新

実行:
  python send_emails.py               # 通常実行（最大30件）
  python send_emails.py --dry-run     # 送信せずプレビュー
  python send_emails.py --limit 10    # 10件だけ送る
  python send_emails.py --test-to me@example.com  # 自分宛テスト送信
  python send_emails.py --force-send  # 時間帯チェックを無視
"""
import argparse
import csv
import os
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_DIR = Path(__file__).parent
DRAFT_FILE = _DIR / "emails_draft.csv"
SENT_LOG = _DIR / "sent_log.csv"
OPT_OUT_FILE = _DIR / "opt_out.csv"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_DIR.parent.parent.parent.parent / ".env")
except ImportError:
    pass

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

DAILY_LIMIT = 30
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


def _load_sent() -> set[str]:
    if not SENT_LOG.exists():
        return set()
    with open(SENT_LOG, encoding="utf-8", newline="") as f:
        return {row["email"] for row in csv.DictReader(f)}


def _load_opt_out() -> set[str]:
    if not OPT_OUT_FILE.exists():
        return set()
    with open(OPT_OUT_FILE, encoding="utf-8", newline="") as f:
        return {row["email"] for row in csv.DictReader(f)}


def add_opt_out(email: str, reason: str = "") -> None:
    existing = _load_opt_out()
    if email in existing:
        print(f"{email} はすでにopt_outリストに登録済みです。")
        return
    write_header = not OPT_OUT_FILE.exists()
    with open(OPT_OUT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["email", "reason", "added_at"])
        if write_header:
            writer.writeheader()
        writer.writerow({"email": email, "reason": reason, "added_at": datetime.now().strftime("%Y-%m-%d %H:%M")})
    print(f"opt_out登録完了: {email}")


def _today_sent_count() -> int:
    if not SENT_LOG.exists():
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    with open(SENT_LOG, encoding="utf-8", newline="") as f:
        return sum(1 for row in csv.DictReader(f) if row.get("sent_at", "").startswith(today))


_COMPANY_REQUIRED = ["株式会社", "有限会社", "合同会社"]
_BLOG_SIGNALS = ["コツ", "方法", "選び方", "ランキング", "名簿", "営業リスト"]


def _check_safety(drafts: list[dict]) -> bool:
    ok = True
    for d in drafts:
        name = d.get("company_name", "")
        if any(sig in name for sig in _BLOG_SIGNALS):
            print(f"WARNING: {d['email']} — 会社名がブログタイトルの可能性: 「{name[:30]}」")
            ok = False
        elif name and not any(kw in name for kw in _COMPANY_REQUIRED):
            print(f"WARNING: {d['email']} — 法人格なし: 「{name[:30]}」")
            ok = False
        body = d.get("body", "")
        missing = []
        if "真柄" not in body:
            missing.append("送信者名")
        if "配信停止" not in body:
            missing.append("配信停止文言")
        if "住所" not in body:
            missing.append("住所")
        if "※要設定" in body:
            missing.append("住所（未設定）")
        if missing:
            print(f"WARNING: {d['email']} — 特定電子メール法違反の可能性: {', '.join(missing)}")
            ok = False
    return ok


def main(limit: int = DAILY_LIMIT, dry_run: bool = False, test_to: str = "", force_send: bool = False):
    if not dry_run and not test_to:
        now_jst = (datetime.now(timezone.utc).hour + 9) % 24
        if not force_send and not (9 <= now_jst < 18):
            print(f"送信停止: 現在 JST {now_jst}時台です（送信は JST 9:00〜18:00）。--force-send で強制送信。")
            return

    if not DRAFT_FILE.exists():
        print("emails_draft.csv が見つかりません。generate_emails.py を先に実行してください。")
        return

    with open(DRAFT_FILE, encoding="utf-8", newline="") as f:
        drafts = list(csv.DictReader(f))

    if test_to:
        if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
            print("環境変数 GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です。")
            return
        draft = next((d for d in drafts if d.get("status") == "draft"), None) or (drafts[0] if drafts else None)
        if not draft:
            print("ドラフトが1件もありません。")
            return
        print(f"テスト送信: {test_to}")
        ok = _send(test_to, f"【テスト】{draft['subject']}", draft["body"])
        print("成功" if ok else "失敗")
        return

    if dry_run:
        already_sent = _load_sent()
        targets = [d for d in drafts if d.get("status") == "draft" and d["email"] not in already_sent][:limit]
        print(f"\nDRY-RUN: 送信予定 {len(targets)}件")
        for i, d in enumerate(targets, 1):
            print(f"[{i:2}] {d['company_name'][:30]:<30} | {d['email']}")
            print(f"     件名: {d['subject']}")
        return

    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("環境変数が未設定: GMAIL_ADDRESS / GMAIL_APP_PASSWORD")
        return

    already_sent = _load_sent()
    opt_out = _load_opt_out()
    today_count = _today_sent_count()
    remaining = limit - today_count

    if remaining <= 0:
        print(f"本日の送信上限（{limit}件）に達しています。")
        return

    print(f"本日送信済み: {today_count}件 / 残り: {remaining}件")
    targets = [d for d in drafts if d.get("status") == "draft" and d["email"] not in already_sent and d["email"] not in opt_out]
    targets = targets[:remaining]
    print(f"送信対象: {len(targets)}件")

    if not targets:
        print("送信対象がありません。pipeline.py を実行してリードを補充してください。")
        return

    if not _check_safety(targets):
        print("\n安全チェックに失敗しました。--dry-run で内容を確認してください。")
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

    draft_fields = list(drafts[0].keys()) if drafts else ["company_name", "email", "subject", "body", "url", "status"]
    updated = []
    for row in drafts:
        if row["email"] in sent_emails:
            row["status"] = "sent"
        updated.append(row)

    with open(DRAFT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=draft_fields)
        writer.writeheader()
        writer.writerows(updated)

    print(f"\n完了。送信成功: {len(sent_emails)}件")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DAILY_LIMIT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test-to", type=str, default="")
    parser.add_argument("--force-send", action="store_true")
    parser.add_argument("--add-opt-out", type=str, default="")
    parser.add_argument("--opt-out-reason", type=str, default="返信による申し出")
    args = parser.parse_args()

    if args.add_opt_out:
        add_opt_out(args.add_opt_out, args.opt_out_reason)
    else:
        main(limit=args.limit, dry_run=args.dry_run, test_to=args.test_to, force_send=args.force_send)
