"""
入金確認後にアクセスコードを発行する。

使い方:
  python gen_access_code.py --company "株式会社〇〇" --plan standard

出力:
  - Supabase にコードを保存
  - 顧客へのメール本文をターミナルに表示
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent / "../../.env")

from db import issue_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True, help="会社名")
    parser.add_argument("--plan", default="standard", choices=["standard", "pro"])
    args = parser.parse_args()

    code = issue_code(args.company, args.plan)

    print(f"\n{'='*50}")
    print(f"会社名  : {args.company}")
    print(f"プラン  : {args.plan}")
    print(f"コード  : {code}")
    print(f"{'='*50}")
    print(f"""
【顧客へのメール本文】

{args.company} ご担当者様

この度はFudoTextをご契約いただきありがとうございます。

以下のアクセスコードをアプリの「コードで解除する」欄に入力してください。

アクセスコード: {code}

ご不明な点はお気軽にお問い合わせください。
ryuumg03@gmail.com
""")


if __name__ == "__main__":
    main()
