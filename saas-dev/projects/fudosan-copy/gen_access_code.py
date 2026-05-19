"""
入金確認後にアクセスコードを発行してメールを自動送信する。

使い方:
  python gen_access_code.py --company "株式会社〇〇" --plan standard --to info@example.co.jp
  python gen_access_code.py --company "株式会社〇〇" --plan standard --to info@example.co.jp --dry-run
"""
import argparse
import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent / "../../.env")

from db import issue_code

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
APP_URL = "https://fudotext.streamlit.app"


def _send_email(to: str, subject: str, body: str) -> bool:
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = to
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"送信エラー: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True, help="会社名")
    parser.add_argument("--plan", default="standard", choices=["standard", "pro"])
    parser.add_argument("--to", required=True, help="送信先メールアドレス")
    parser.add_argument("--dry-run", action="store_true", help="送信せずプレビューのみ")
    args = parser.parse_args()

    plan_label = "スタンダード（月50件）" if args.plan == "standard" else "プロ（月200件）"

    code = issue_code(args.company, args.plan)

    subject = "【FudoText】アクセスコードのご案内"
    body = f"""{args.company} ご担当者様

この度はFudoTextをご契約いただきありがとうございます。

プラン: {plan_label}
アクセスコード: {code}

【使い方】
1. 以下のURLにアクセスしてください
   {APP_URL}
2. メールアドレスを入力してトライアルを開始
3. 上限に達したら「アクセスコードをお持ちの方」に上記コードを入力

ご不明な点はお気軽にご返信ください。

━━━━━━━━━━━━━━━━━━
FudoText 開発者
Mail: {GMAIL_ADDRESS}
━━━━━━━━━━━━━━━━━━
"""

    print(f"\n{'='*50}")
    print(f"会社名  : {args.company}")
    print(f"プラン  : {args.plan}")
    print(f"宛先    : {args.to}")
    print(f"コード  : {code}")
    print(f"{'='*50}")
    print(f"\n--- メール本文 ---\n{body}")

    if args.dry_run:
        print("【dry-run】送信はスキップしました。")
        return

    print("送信中...")
    if _send_email(args.to, subject, body):
        print(f"送信完了: {args.to}")
    else:
        print("送信失敗。メールアドレスと環境変数を確認してください。")


if __name__ == "__main__":
    main()
