#!/usr/bin/env python3
"""
manual_outreach.py — スコアリングをバイパスして手動リストに直接メール送信

使い方:
  python shared/gtm/scripts/manual_outreach.py --product sharotext --csv my_list.csv
  python shared/gtm/scripts/manual_outreach.py --product sharotext --csv my_list.csv --dry-run
  python shared/gtm/scripts/manual_outreach.py --product sharotext --csv my_list.csv --limit 20

CSVフォーマット（必須カラム）:
  company_name,email
  株式会社サンプル,info@example.co.jp
  ...

オプション追加カラム（あれば使用）:
  url, prefecture

フロー:
  1. CSVを読み込み
  2. 送信予定の会社名リストを表示してユーザーに確認を求める
  3. 確認後、{product}の config + template でメール草稿を生成
  4. emails_draft.csv に追記 → send_emails.py の _send() で送信
"""

import argparse
import csv
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

AI_HOLDINGS = Path(__file__).resolve().parent.parent.parent.parent
GTM_DIR = AI_HOLDINGS / "shared" / "gtm"
SAAS_PROJECTS_DIR = AI_HOLDINGS / "saas-dev" / "projects"

# .envを読む
try:
    env_path = AI_HOLDINGS / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if v and k.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()
except Exception:
    pass

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

DAILY_LIMIT = 30
SEND_INTERVAL = 30  # 秒


# ── 設定 / テンプレート読み込み ──────────────────────────────────────────────────

def _load_config(product: str) -> dict:
    path = GTM_DIR / "config" / f"{product}.json"
    if not path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _load_template(cfg: dict) -> str:
    template_file = cfg.get("email_template", {}).get("template_file", "")
    if not template_file:
        raise ValueError("config に email_template.template_file が未設定です")
    path = GTM_DIR / "outreach" / "templates" / template_file
    if not path.exists():
        raise FileNotFoundError(f"テンプレートが見つかりません: {path}")
    return path.read_text(encoding="utf-8")


# ── Gemini パーソナライズ ──────────────────────────────────────────────────────

def _gemini_personalize(company_name: str, prompt_template: str, model: str) -> str:
    """Gemini で書き出し文を生成。失敗時はフォールバック文を返す"""
    if not GEMINI_KEY:
        return ""
    prompt = prompt_template.format(company_name=company_name)
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 100, "temperature": 0.7},
    }).encode()
    api_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={GEMINI_KEY}"
    )
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                api_url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** (attempt + 1)
                print(f"    Gemini 429 → {wait}s待機...")
                time.sleep(wait)
            else:
                return ""
        except Exception:
            return ""
    return ""


# ── CSV読み込み ───────────────────────────────────────────────────────────────

def _load_input_csv(csv_path: Path) -> list[dict]:
    """入力CSVを読んでバリデーション"""
    if not csv_path.exists():
        raise FileNotFoundError(f"CSVファイルが見つかりません: {csv_path}")

    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise ValueError("CSVが空です")

    # 必須カラム確認
    required = {"company_name", "email"}
    actual = set(rows[0].keys())
    missing = required - actual
    if missing:
        raise ValueError(
            f"必須カラムが不足しています: {missing}\n"
            f"  現在のカラム: {actual}\n"
            f"  必須: company_name, email"
        )

    return rows


# ── メール送信 ────────────────────────────────────────────────────────────────

def _send_email(to: str, subject: str, body: str) -> bool:
    """Gmail SMTP でメールを1通送信"""
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


# ── 送信済みセット ────────────────────────────────────────────────────────────

def _load_sent_emails(project_dir: Path) -> set[str]:
    sent = set()
    for fname in ["sent_log.csv", "emails_draft.csv"]:
        path = project_dir / "outreach" / fname
        if path.exists():
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    if email := row.get("email", "").strip():
                        sent.add(email.lower())
    return sent


# ── 安全チェック ──────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

def _validate_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email.strip()))


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="手動リストにコールドメールを直接送信",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CSVフォーマット（必須）:
  company_name,email
  株式会社サンプル,info@example.co.jp

例:
  python manual_outreach.py --product sharotext --csv leads.csv --dry-run
  python manual_outreach.py --product sharotext --csv leads.csv --limit 10
        """,
    )
    parser.add_argument("--product", required=True, help="製品スラッグ（例: sharotext）")
    parser.add_argument("--csv", required=True, help="入力CSVファイルパス（company_name,email）")
    parser.add_argument("--dry-run", action="store_true", help="送信せずに会社名リストのみ表示")
    parser.add_argument("--limit", type=int, default=DAILY_LIMIT, help=f"送信上限件数（デフォルト: {DAILY_LIMIT}）")
    parser.add_argument("--skip-sent", action="store_true", default=True,
                        help="既送信メールアドレスをスキップ（デフォルト: on）")
    parser.add_argument("--no-skip-sent", action="store_false", dest="skip_sent",
                        help="既送信チェックをスキップ")
    parser.add_argument("--force-send", action="store_true",
                        help="JST 9:00-18:00 以外でも強制送信")
    args = parser.parse_args()

    csv_path = Path(args.csv)

    # 時刻チェック（dry-runは除外）
    if not args.dry_run and not args.force_send:
        now_jst = (datetime.now(timezone.utc).hour + 9) % 24
        if not (9 <= now_jst < 18):
            print(f"送信停止: 現在 JST {now_jst}時台です（送信は JST 9:00〜18:00）。--force-send で強制送信。")
            return

    # 設定読み込み
    print(f"製品設定を読み込み中: {args.product}")
    try:
        cfg = _load_config(args.product)
        template = _load_template(cfg)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    product_name = cfg["product_name"]
    project_dir_name = cfg.get("project_dir", args.product)
    project_dir = SAAS_PROJECTS_DIR / project_dir_name
    sender_address = os.environ.get("SENDER_ADDRESS", cfg.get("sender_address", ""))

    print(f"製品: {product_name}")
    print(f"テンプレート: {cfg['email_template']['template_file']}")

    # CSV読み込み
    print(f"\nCSV読み込み中: {csv_path}")
    try:
        rows = _load_input_csv(csv_path)
    except (FileNotFoundError, ValueError) as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # メールアドレスのバリデーション
    valid_rows = []
    skipped_invalid = 0
    for row in rows:
        email = row.get("email", "").strip()
        company = row.get("company_name", "").strip()
        if not email or not company:
            print(f"  SKIP（空欄）: company={company!r}, email={email!r}")
            skipped_invalid += 1
            continue
        if not _validate_email(email):
            print(f"  SKIP（無効メール）: {email}")
            skipped_invalid += 1
            continue
        valid_rows.append({**row, "email": email, "company_name": company})

    print(f"有効: {len(valid_rows)}件 / 無効スキップ: {skipped_invalid}件")

    # 既送信スキップ
    already_sent = set()
    if args.skip_sent:
        already_sent = _load_sent_emails(project_dir)
        before = len(valid_rows)
        valid_rows = [r for r in valid_rows if r["email"].lower() not in already_sent]
        skipped_sent = before - len(valid_rows)
        if skipped_sent > 0:
            print(f"送信済みスキップ: {skipped_sent}件")

    # 上限適用
    targets = valid_rows[:args.limit]

    if not targets:
        print("\n送信対象が0件です。")
        return

    # ─────────────────────────────────────────────────────────
    # 送信前確認ゲート（必須）
    # ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"送信予定リスト ({len(targets)}件):")
    print(f"{'='*60}")
    print(f"{'#':>3}  {'会社名':<35} {'メールアドレス'}")
    print(f"{'-'*3}  {'-'*35} {'-'*30}")
    for i, row in enumerate(targets, 1):
        company = row["company_name"]
        email = row["email"]
        print(f"{i:>3}.  {company[:35]:<35} {email}")
    print(f"{'='*60}")
    print(f"製品: {product_name}")
    print(f"件名: {cfg['email_template']['subject']}")
    print(f"送信上限: {args.limit}件 / 間隔: {SEND_INTERVAL}秒")
    print(f"{'='*60}\n")

    if args.dry_run:
        print("DRY-RUN モード: 上記の内容を確認しました。実際の送信は行いません。")
        print("\nヒント: --dry-run を外すと実際に送信されます。")
        return

    # 環境変数チェック
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("ERROR: 環境変数が未設定です。")
        print("  GMAIL_ADDRESS — 送信元Gmailアドレス")
        print("  GMAIL_APP_PASSWORD — Googleアカウントのアプリパスワード")
        sys.exit(1)

    # 確認入力
    print("上記のリストにメールを送信します。")
    try:
        confirm = input("続行しますか？ [yes/no]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n中断しました。")
        return

    if confirm not in ("yes", "y"):
        print("キャンセルしました。")
        return

    # ─────────────────────────────────────────────────────────
    # メール草稿生成 + 送信
    # ─────────────────────────────────────────────────────────
    model = cfg.get("gemini_model", "gemini-2.0-flash-lite")
    fallback_opening = cfg["email_template"]["fallback_opening"]
    personalize_prompt = cfg["email_template"]["personalize_prompt"]
    subject = cfg["email_template"]["subject"]

    # emails_draft.csv への追記設定
    draft_file = project_dir / "outreach" / "emails_draft.csv"
    sent_log = project_dir / "outreach" / "sent_log.csv"
    draft_fields = ["company_name", "email", "subject", "body", "url", "status", "personalized"]

    draft_file.parent.mkdir(parents=True, exist_ok=True)
    write_draft_header = not draft_file.exists()

    # sent_log 追記設定
    write_sent_header = not sent_log.exists()
    sent_count = 0
    sent_emails = set()

    print(f"\n送信開始... ({len(targets)}件)\n")

    with open(draft_file, "a", newline="", encoding="utf-8") as df, \
         open(sent_log, "a", newline="", encoding="utf-8") as lf:

        draft_writer = csv.DictWriter(df, fieldnames=draft_fields)
        log_writer = csv.DictWriter(
            lf,
            fieldnames=["company_name", "email", "subject", "sent_at", "result", "source"],
        )
        if write_draft_header:
            draft_writer.writeheader()
        if write_sent_header:
            log_writer.writeheader()

        for i, row in enumerate(targets, 1):
            company = row["company_name"]
            email = row["email"]
            url = row.get("url", "")
            print(f"  [{i}/{len(targets)}] {company[:35]} <{email}>", end=" ... ")

            # パーソナライズ書き出し文生成
            opening = _gemini_personalize(company, personalize_prompt, model)
            personalized = bool(opening)
            if not opening:
                opening = fallback_opening

            # メール本文を組み立て
            try:
                body = template.format(
                    company_name=company,
                    sender_name=cfg["sender_name"],
                    product_name=cfg["product_name"],
                    app_url=cfg["app_url"],
                    lp_url=cfg["lp_url"],
                    sender_email=cfg["sender_email"],
                    sender_address=sender_address,
                    personalized_opening=opening,
                )
            except KeyError as e:
                print(f"テンプレートキーエラー: {e} — スキップ")
                continue

            # 草稿保存
            draft_writer.writerow({
                "company_name": company,
                "email": email,
                "subject": subject,
                "body": body,
                "url": url,
                "status": "draft",
                "personalized": str(personalized),
            })
            df.flush()

            # 送信
            ok = _send_email(email, subject, body)
            result = "sent" if ok else "failed"
            print(f"{'AI' if personalized else 'FB'} → {result}")

            log_writer.writerow({
                "company_name": company,
                "email": email,
                "subject": subject,
                "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "result": result,
                "source": "manual_outreach",
            })
            lf.flush()

            if ok:
                sent_count += 1
                sent_emails.add(email)

            if i < len(targets):
                time.sleep(SEND_INTERVAL)

    # emails_draft.csv の status を sent に更新
    if sent_emails and draft_file.exists():
        with open(draft_file, "r", encoding="utf-8", newline="") as f:
            all_drafts = list(csv.DictReader(f))
        updated = []
        for row in all_drafts:
            if row.get("email", "").lower() in {e.lower() for e in sent_emails}:
                row["status"] = "sent"
            updated.append(row)
        fields = list(all_drafts[0].keys()) if all_drafts else draft_fields
        with open(draft_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(updated)

    print(f"\n完了。送信成功: {sent_count}件 / 送信試行: {len(targets)}件")
    print(f"ログ: {sent_log}")


if __name__ == "__main__":
    main()
