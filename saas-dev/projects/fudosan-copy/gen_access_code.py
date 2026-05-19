"""
入金確認後にアクセスコードを発行する。

使い方:
  python gen_access_code.py --company "株式会社〇〇" --plan standard

出力:
  - コード（UUIDv4）をターミナルに表示
  - Streamlit Secrets への追記方法を案内
"""
import argparse
import uuid
import datetime

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True, help="会社名")
    parser.add_argument("--plan", default="standard", choices=["standard", "pro"])
    args = parser.parse_args()

    code = str(uuid.uuid4())
    today = datetime.date.today().isoformat()

    print(f"\n{'='*50}")
    print(f"会社名  : {args.company}")
    print(f"プラン  : {args.plan}")
    print(f"発行日  : {today}")
    print(f"コード  : {code}")
    print(f"{'='*50}")
    secrets_key = "PAID_CODES_PRO" if args.plan == "pro" else "PAID_CODES_STANDARD"
    print(f"\n【Streamlit Secrets への追記】")
    print(f"既存の {secrets_key} の末尾に追記してください:\n")
    print(f'{secrets_key} = "既存のコード,{code}"')
    print(f"\n【顧客へのメール本文】")
    print(f"""
{args.company} ご担当者様

この度はFudoTextをご契約いただきありがとうございます。

以下のアクセスコードをアプリの「コードで解除する」欄に入力してください。

アクセスコード: {code}

ご不明な点はお気軽にお問い合わせください。
ryuumg03@gmail.com
""")

if __name__ == "__main__":
    main()
