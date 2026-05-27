"""
デモ1回利用者へのフォローアップメール送信。

各製品の {slug}_trials テーブルで count >= 1 かつ plan IS NULL のユーザーに
1度だけフォローアップメールを送る。送信済みは textseries_followup_log で管理。

Usage:
  python send_demo_followup.py [--dry-run] [--slug caretext] [--limit 10]
"""
import argparse
import json
import os
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CFG_DIR = _ROOT / "shared" / "gtm" / "config"
_REGISTRY = _ROOT / "shared" / "portfolio" / "registry.json"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

SUPABASE_URL      = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_SVC_KEY  = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
GMAIL_ADDRESS     = os.environ.get("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

CLOUD_RUN_BASE = "https://{slug}-cup7okvfwq-an.a.run.app"
LOG_TABLE      = "textseries_followup_log"
SEND_INTERVAL  = 5   # 秒


def _headers() -> dict:
    key = SUPABASE_SVC_KEY or os.environ.get("SUPABASE_ANON_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_get(table: str, query: str = "") -> list:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if query:
        url += f"?{query}"
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _sb_post(table: str, data: dict) -> None:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, headers=_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()


def get_trial_users(slug: str) -> list[str]:
    """count >= 1 かつ未課金のユーザーメール一覧を返す。テーブルなければ空リスト。"""
    table = f"{slug}_trials"
    try:
        rows = _sb_get(table, "count=gte.1&plan=is.null&select=email")
        return [r["email"] for r in rows if r.get("email")]
    except urllib.error.HTTPError as e:
        if e.code in (404, 400):
            return []
        raise


def get_sent_emails(slug: str) -> set[str]:
    try:
        rows = _sb_get(LOG_TABLE, f"slug=eq.{urllib.parse.quote(slug)}&select=email")
        return {r["email"] for r in rows}
    except urllib.error.HTTPError as e:
        if e.code in (404, 400):
            return set()
        raise


def log_sent(slug: str, email: str) -> None:
    _sb_post(LOG_TABLE, {"slug": slug, "email": email})


def build_email(slug: str, product_name: str, to_email: str) -> tuple[str, str]:
    url = CLOUD_RUN_BASE.format(slug=slug)
    subject = f"【{product_name}】お試しいただきありがとうございます"
    body = f"""\
いつもお世話になっております。

{product_name} をお試しいただき、ありがとうございます。

少しでもお役に立てましたでしょうか？

「こんな書類も作れたら嬉しい」「ここが使いにくかった」など、
些細なご意見でもこのメールに直接ご返信いただけると大変助かります。
すべて目を通し、改善に活かしてまいります。

引き続きご利用いただける場合はこちらから：
{url}

どうぞよろしくお願いいたします。

---
{product_name} 運営
{GMAIL_ADDRESS}
"""
    return subject, body


def send_email(to: str, subject: str, body: str) -> bool:
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"]    = GMAIL_ADDRESS
        msg["To"]      = to
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"    送信失敗: {e}")
        return False


def load_product_name(slug: str) -> str:
    cfg_path = _CFG_DIR / f"{slug}.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            name = cfg.get("product_name", "")
            if name:
                return name
        except Exception:
            pass
    return slug.capitalize()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug",    help="特定製品のみ")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit",   type=int, default=50, help="1回の最大送信数")
    args = parser.parse_args()

    if not SUPABASE_URL:
        print("SUPABASE_URL が未設定"); sys.exit(1)
    if not args.dry_run and (not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD):
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定"); sys.exit(1)

    registry = json.loads(_REGISTRY.read_text(encoding="utf-8"))
    slugs = [args.slug] if args.slug else [p["slug"] for p in registry]

    total_sent, total_skip = 0, 0

    for slug in slugs:
        product_name = load_product_name(slug)
        try:
            trial_users = get_trial_users(slug)
        except Exception as e:
            print(f"[{slug}] trials取得失敗: {e}")
            continue

        if not trial_users:
            continue

        try:
            sent_set = get_sent_emails(slug)
        except Exception as e:
            print(f"[{slug}] log取得失敗: {e}")
            continue

        targets = [e for e in trial_users if e not in sent_set]
        if not targets:
            continue

        print(f"\n[{product_name}] 対象: {len(targets)}件")

        for email in targets:
            if total_sent >= args.limit:
                print(f"  上限({args.limit}件)に達しました")
                break

            subject, body = build_email(slug, product_name, email)

            if args.dry_run:
                print(f"  [dry-run] → {email}")
                total_sent += 1
                continue

            ok = send_email(email, subject, body)
            if ok:
                try:
                    log_sent(slug, email)
                except Exception as e:
                    print(f"    ログ記録失敗: {e}")
                print(f"  ✓ {email}")
                total_sent += 1
                time.sleep(SEND_INTERVAL)
            else:
                total_skip += 1

    print(f"\n{'='*50}")
    print(f"送信完了: {total_sent}件 / 失敗: {total_skip}件")


if __name__ == "__main__":
    main()
