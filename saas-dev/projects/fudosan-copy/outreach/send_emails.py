"""
Gmail SMTP で自動送信（30件/日）
入力: emails_draft.csv (status=draft のもの)
出力: sent_log.csv + emails_draft.csv の status を sent に更新

事前準備:
  1. Googleアカウント → セキュリティ → 2段階認証 ON
  2. アプリパスワード生成（16文字）
  3. 環境変数に設定:
     GMAIL_ADDRESS=ryuumg03@gmail.com
     GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

実行:
  python send_emails.py                 # 通常実行（最大30件）
  python send_emails.py --dry-run       # 送信せずプレビュー
  python send_emails.py --preview 3     # 3番目のドラフト本文を全表示
  python send_emails.py --limit 10      # 10件だけ送る
  python send_emails.py --test-to me@example.com  # 自分宛にテスト送信
"""
import argparse
import csv
import io
import os
import smtplib
import sys
import time
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_DIR = Path(__file__).parent
DRAFT_FILE = _DIR / "emails_draft.csv"
SENT_LOG = _DIR / "sent_log.csv"

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

DAILY_LIMIT = 30  # Gmailの信頼スコア保護のため上限を抑える
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


def _check_safety(drafts: list[dict], limit: int) -> bool:
    """送信前の安全チェック。問題があれば警告してFalseを返す"""
    ok = True
    if limit > 30:
        print(f"WARNING: --limit {limit} は30件超です。Gmailの信頼スコアへの影響に注意してください。")

    # personalized列がある場合: フォールバック率チェック
    if drafts and "personalized" in drafts[0]:
        fp_count = sum(1 for d in drafts if d.get("personalized", "").lower() == "false")
        if fp_count / len(drafts) > 0.2:
            print(f"WARNING: パーソナライズ失敗率が高い ({fp_count}/{len(drafts)}件)。Gemini 429が多発していた可能性があります。")

    # 特定電子メール法文言チェック
    for d in drafts:
        body = d.get("body", "")
        if "ご不要" not in body or "真柄" not in body:
            print(f"WARNING: {d['email']} — オプトアウト文言または送信者本名が見当たりません。")
            ok = False
    return ok


def _preview_drafts(drafts: list[dict], limit: int) -> None:
    """--dry-run 用: 送信予定の一覧をターミナルに出力"""
    already_sent = _load_sent()
    targets = [d for d in drafts if d.get("status") == "draft" and d["email"] not in already_sent]
    targets = targets[:limit]
    print(f"\n{'='*60}")
    print(f"DRY-RUN: 送信予定 {len(targets)}件（実際には送信しません）")
    print(f"{'='*60}")
    for i, d in enumerate(targets, 1):
        personalized = d.get("personalized", "?")
        print(f"[{i:2}] {d['company_name'][:28]:<28} | {d['email']}")
        print(f"     件名: {d['subject']}")
        print(f"     本文冒頭: {d['body'][:80].replace(chr(10), ' ')}")
        print(f"     パーソナライズ: {personalized}")
        print()
    print(f"合計 {len(targets)}件を送信予定でした（実際には送信しませんでした）")


def main(limit: int = DAILY_LIMIT, dry_run: bool = False, preview_n: int = 0, test_to: str = ""):
    if not DRAFT_FILE.exists():
        print("emails_draft.csv が見つかりません。generate_emails.py を先に実行してください。")
        return

    with open(DRAFT_FILE, encoding="utf-8", newline="") as f:
        drafts = list(csv.DictReader(f))

    # --preview N: N番目のドラフト本文全表示
    if preview_n > 0:
        idx = preview_n - 1
        if idx >= len(drafts):
            print(f"ドラフトは{len(drafts)}件しかありません。")
            return
        d = drafts[idx]
        print(f"\n{'='*60}")
        print(f"[{preview_n}] {d['company_name']} <{d['email']}>")
        print(f"件名: {d['subject']}")
        print(f"{'='*60}")
        print(d["body"])
        print(f"{'='*60}")
        return

    # --test-to: 自分宛てテスト送信
    if test_to:
        if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
            print("環境変数 GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定です。")
            return
        draft = next((d for d in drafts if d.get("status") == "draft"), None)
        if not draft:
            print("送信可能なドラフトがありません。")
            return
        print(f"テスト送信: {test_to}")
        ok = _send(test_to, f"【テスト】{draft['subject']}", draft["body"])
        print("成功" if ok else "失敗")
        return

    # --dry-run: プレビューのみ
    if dry_run:
        _preview_drafts(drafts, limit)
        return

    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("環境変数が未設定です:")
        print("  $env:GMAIL_ADDRESS='ryuumg03@gmail.com'")
        print("  $env:GMAIL_APP_PASSWORD='アプリパスワード'")
        return

    already_sent = _load_sent()
    today_count = _today_sent_count()
    remaining = limit - today_count

    if remaining <= 0:
        print(f"本日の送信上限（{limit}件）に達しています。明日再実行してください。")
        return

    print(f"本日送信済み: {today_count}件 / 残り: {remaining}件")

    targets = [d for d in drafts if d.get("status") == "draft" and d["email"] not in already_sent]
    targets = targets[:remaining]
    print(f"送信対象: {len(targets)}件")

    if not targets:
        print("送信対象がありません。collect_leads.py → generate_emails.py を実行してください。")
        return

    if not _check_safety(targets, limit):
        print("\n安全チェックに失敗しました。内容を確認してから再実行してください。")
        print("確認するには: python send_emails.py --dry-run")
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

    success = len(sent_emails)
    print(f"\n完了。送信成功: {success}件")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DAILY_LIMIT)
    parser.add_argument("--dry-run", action="store_true", help="送信せずプレビューのみ")
    parser.add_argument("--preview", type=int, metavar="N", default=0, help="N番目のドラフト本文を全表示")
    parser.add_argument("--test-to", type=str, default="", metavar="EMAIL", help="指定メアドにテスト送信")
    args = parser.parse_args()
    main(limit=args.limit, dry_run=args.dry_run, preview_n=args.preview, test_to=args.test_to)
