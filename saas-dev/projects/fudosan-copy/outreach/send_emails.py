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
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass  # pytest / non-reconfigurable stdout

_DIR = Path(__file__).parent
DRAFT_FILE = _DIR / "emails_draft.csv"
SENT_LOG = _DIR / "sent_log.csv"
OPT_OUT_FILE = _DIR / "opt_out.csv"

from dotenv import load_dotenv
load_dotenv(dotenv_path=_DIR.parent.parent.parent.parent / ".env")

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


def _load_opt_out() -> set[str]:
    if not OPT_OUT_FILE.exists():
        return set()
    with open(OPT_OUT_FILE, encoding="utf-8", newline="") as f:
        return {row["email"] for row in csv.DictReader(f)}


def add_opt_out(email: str, reason: str = "") -> None:
    """配信停止申し出のあったメールアドレスを記録する"""
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


def _check_safety(drafts: list[dict], limit: int) -> bool:
    """送信前の安全チェック。問題があれば警告してFalseを返す"""
    ok = True
    if limit > 30:
        print(f"WARNING: --limit {limit} は30件超です。Gmailの信頼スコアへの影響に注意してください。")

    # 会社名チェック: ブログタイトルや未抽出の会社名が混入していないか
    _company_required = ["株式会社", "有限会社", "合同会社", "一般社団法人"]
    _blog_signals = ["コツ", "方法", "選び方", "探し方", "ランキング", "名簿", "営業リスト", "お問い合わせ |", "お問い合わせ｜"]
    for d in drafts:
        name = d.get("company_name", "")
        if any(sig in name for sig in _blog_signals):
            print(f"WARNING: {d['email']} — 会社名がブログタイトルの可能性: 「{name[:30]}」")
            ok = False

    # personalized列がある場合: フォールバック率チェック
    if drafts and "personalized" in drafts[0]:
        fp_count = sum(1 for d in drafts if d.get("personalized", "").lower() == "false")
        if fp_count / len(drafts) > 0.2:
            print(f"WARNING: パーソナライズ失敗率が高い ({fp_count}/{len(drafts)}件)。Gemini 429が多発していた可能性があります。")

    # 特定電子メール法文言チェック
    for d in drafts:
        body = d.get("body", "")
        missing = []
        if "真柄" not in body:
            missing.append("送信者名")
        if "配信停止" not in body:
            missing.append("配信停止文言")
        if "住所" not in body:
            missing.append("住所")
        if "※要設定" in body:
            missing.append("住所（未設定: .envのSENDER_ADDRESSを設定してください）")
        if missing:
            print(f"WARNING: {d['email']} — 特定電子メール法違反の可能性: {', '.join(missing)}")
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


def main(limit: int = DAILY_LIMIT, dry_run: bool = False, preview_n: int = 0, test_to: str = "", force_send: bool = False):
    # 送信可能時間帯チェックを最初に行う（ファイル確認より先）
    if not dry_run and not preview_n and not test_to:
        now_jst = (datetime.now(timezone.utc).hour + 9) % 24
        if not force_send and not (9 <= now_jst < 18):
            print(f"送信停止: 現在 JST {now_jst}時台です。")
            print("ビジネスメールの送信は JST 9:00〜18:00 に限定しています。")
            print("時間帯を無視して送信する場合は --force-send フラグを使用してください。")
            return

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
        draft = next((d for d in drafts if d.get("status") == "draft"), None) or (drafts[0] if drafts else None)
        if not draft:
            print("ドラフトが1件もありません。")
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
    opt_out = _load_opt_out()
    today_count = _today_sent_count()
    remaining = limit - today_count

    if remaining <= 0:
        print(f"本日の送信上限（{limit}件）に達しています。明日再実行してください。")
        return

    print(f"本日送信済み: {today_count}件 / 残り: {remaining}件")
    if opt_out:
        print(f"opt_outリスト: {len(opt_out)}件（送信除外）")

    targets = [d for d in drafts if d.get("status") == "draft" and d["email"] not in already_sent and d["email"] not in opt_out]
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
    parser.add_argument("--force-send", action="store_true", help="時間帯チェックを無視して送信（非推奨）")
    parser.add_argument("--add-opt-out", type=str, default="", metavar="EMAIL", help="配信停止申し出のメールアドレスをopt_outリストに追加")
    parser.add_argument("--opt-out-reason", type=str, default="返信による申し出", help="opt_out登録理由")
    args = parser.parse_args()

    if args.add_opt_out:
        add_opt_out(args.add_opt_out, args.opt_out_reason)
    else:
        main(limit=args.limit, dry_run=args.dry_run, preview_n=args.preview, test_to=args.test_to, force_send=args.force_send)
