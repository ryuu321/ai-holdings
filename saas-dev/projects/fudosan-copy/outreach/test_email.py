"""
テストメール送信 — 自分のGmailに1件送って表示を確認する
実行: python test_email.py
"""
import os
import smtplib
from email.mime.text import MIMEText
from pathlib import Path

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

BODY = """株式会社サンプル不動産
ご担当者様

突然のご連絡、失礼いたします。
不動産仲介業者向けAIツール「FudoText」を開発しております、真柄龍聖と申します。

物件説明文の作成業務において、ご担当者様のお時間を少しでも省けるのではと思い、ご連絡させていただきました。

■ FudoTextでできること
・SUUMO（400字）・at home（500字）・HOMES（450字）に自動対応
・ターゲット（ファミリー/投資家/単身者）を選ぶだけで訴求内容を自動最適化
・景品表示法に違反する表現を自動チェック
・登録不要・完全無料でお試しいただけます

■ 生成時間の目安
物件情報の入力: 約30秒 → AI生成: 約15秒 → 合計45秒で完成

無料でお試しいただけます:
https://ai-holdings-jarqe7ynu8kkyqsuxdrabs.streamlit.app/

ご不明な点はお気軽にご返信ください。
ご不要の場合はその旨ご返信いただければ、以降はご連絡いたしません。

━━━━━━━━━━━━━━━━━━
真柄 龍聖
FudoText 開発者
Mail: ryuumg03@gmail.com
Web: https://ryuu321.github.io/ai-holdings/docs/fudotext.html
━━━━━━━━━━━━━━━━━━"""


def main():
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("環境変数が未設定です:")
        print("  $env:GMAIL_ADDRESS='ryuumg03@gmail.com'")
        print("  $env:GMAIL_APP_PASSWORD='アプリパスワード'")
        return

    msg = MIMEText(BODY, "plain", "utf-8")
    msg["Subject"] = "【テスト】FudoTextメール表示確認"
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = GMAIL_ADDRESS

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        smtp.send_message(msg)

    print(f"送信完了: {GMAIL_ADDRESS}")
    print("Gmailを開いて表示を確認してください。")


if __name__ == "__main__":
    main()
