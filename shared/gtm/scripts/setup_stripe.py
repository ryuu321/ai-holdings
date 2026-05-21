"""
Stripe 製品・価格・決済リンクを自動作成するセットアップスクリプト。

Usage:
  python shared/gtm/scripts/setup_stripe.py --project sharotext
  python shared/gtm/scripts/setup_stripe.py --project kentext

必要な環境変数:
  STRIPE_SECRET_KEY — Stripe ダッシュボード → Developers → API keys → Secret key

完了後: clipboard.txt に Streamlit Secrets 用の設定が出力される。
"""
import argparse
import json
import os
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CFG_DIR = _ROOT / "shared" / "gtm" / "config"

PLANS = [
    {"key": "standard", "label": "スタンダード", "amount": 8980,  "limit": "月50件"},
    {"key": "pro",      "label": "プロ",         "amount": 19800, "limit": "月200件"},
]


def _req(method: str, path: str, data: dict | None, api_key: str) -> dict:
    url = f"https://api.stripe.com/v1/{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read())
        raise RuntimeError(f"Stripe API エラー ({e.code}): {err.get('error', {}).get('message', '')}") from None


def create_product(name: str, description: str, api_key: str) -> str:
    result = _req("POST", "products", {"name": name, "description": description}, api_key)
    return result["id"]


def create_price(product_id: str, amount: int, api_key: str) -> str:
    result = _req("POST", "prices", {
        "product": product_id,
        "unit_amount": amount,
        "currency": "jpy",
        "recurring[interval]": "month",
    }, api_key)
    return result["id"]


def create_payment_link(price_id: str, api_key: str) -> str:
    result = _req("POST", "payment_links", {
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
    }, api_key)
    return result["url"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not api_key:
        print("ERROR: STRIPE_SECRET_KEY が .env に設定されていません。")
        return

    cfg_path = _CFG_DIR / f"{args.project}.json"
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)

    product_name = cfg["product_name"]
    print(f"[{product_name}] Stripe セットアップを開始...")

    urls: dict[str, str] = {}
    for plan in PLANS:
        print(f"  {plan['label']}プラン (¥{plan['amount']:,}/月) を作成中...")
        pid = create_product(
            name=f"{product_name} {plan['label']}プラン",
            description=f"{plan['limit']}生成できる月額プラン",
            api_key=api_key,
        )
        price_id = create_price(pid, plan["amount"], api_key)
        link = create_payment_link(price_id, api_key)
        urls[plan["key"]] = link
        print(f"    → {link}")

    project_upper = args.project.upper()
    secrets_block = f"""{project_upper}_STRIPE_STANDARD_URL = "{urls['standard']}"
{project_upper}_STRIPE_PRO_URL = "{urls['pro']}"
"""

    clipboard_path = _ROOT / "clipboard.txt"
    clipboard_path.write_text(
        f"【{product_name} Stripe設定完了】\n\n"
        f"Streamlit Cloud → sharotext アプリ → Settings → Secrets に追加:\n\n"
        f"{secrets_block}\n"
        f"保存後にアプリが自動再起動されます。\n",
        encoding="utf-8",
    )
    print(f"\n完了。clipboard.txt に Streamlit Secrets 用の設定を出力しました。")


if __name__ == "__main__":
    main()
