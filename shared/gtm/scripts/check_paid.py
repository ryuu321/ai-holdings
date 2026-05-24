"""
Stripe 新規サブスクリプション検出 → アクセスコード生成 → メール送信スクリプト。

Usage:
  python shared/gtm/scripts/check_paid.py --project sharotext
  python shared/gtm/scripts/check_paid.py  # 全18製品を一括チェック

毎時間 GitHub Actions から自動実行される。
送信済みの subscription.id を shared/gtm/state/sent_subscriptions.json に記録して二重送信を防止。

必要なシークレット（GitHub Actions / .env）:
  STRIPE_SECRET_KEY
  SUPABASE_URL
  SUPABASE_ANON_KEY
  SUPABASE_SERVICE_KEY
  GMAIL_ADDRESS
  GMAIL_APP_PASSWORD
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CFG_DIR = _ROOT / "shared" / "gtm" / "config"
_STATE_DIR = _ROOT / "shared" / "gtm" / "state"
_STATE_FILE = _STATE_DIR / "sent_subscriptions.json"

# .envを手動ロード
_env_file = _ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

ALL_PRODUCTS = [
    "aftertext", "caretext", "churntext", "cmtext", "daytext", "denkitext",
    "fudotext", "gyotext", "iintext", "jukutext", "kanritext", "kentext",
    "pharmtext", "sharotext", "shoshitext", "taxtext", "tokutext", "tostext",
]

PLAN_LIMITS = {"standard": 50, "pro": 200}
PLAN_PRICES = {"standard": "¥8,980", "pro": "¥19,800"}
PLAN_LABELS = {"standard": "スタンダード", "pro": "プロ"}


# ─────────────────────────────────────────────
# Stripe API
# ─────────────────────────────────────────────

def _stripe_req(method: str, path: str, data: dict | None = None) -> dict:
    api_key = os.environ["STRIPE_SECRET_KEY"]
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
        err_body = e.read().decode()
        try:
            err = json.loads(err_body)
            msg = err.get("error", {}).get("message", err_body)
        except Exception:
            msg = err_body
        raise RuntimeError(f"Stripe API エラー ({e.code}): {msg}") from None


def get_recent_subscriptions(hours: int = 1) -> list[dict]:
    """過去N時間の新規アクティブサブスクリプションを取得。"""
    since = int(time.time()) - hours * 3600
    subs = []
    params = f"status=active&created[gte]={since}&limit=100&expand[]=data.customer"
    result = _stripe_req("GET", f"subscriptions?{params}")
    subs.extend(result.get("data", []))
    while result.get("has_more"):
        last_id = subs[-1]["id"]
        result = _stripe_req("GET", f"subscriptions?{params}&starting_after={last_id}")
        subs.extend(result.get("data", []))
    return subs


def get_customer_email(customer_id: str) -> str | None:
    """Stripe customer から email を取得。"""
    if not customer_id:
        return None
    try:
        cust = _stripe_req("GET", f"customers/{customer_id}")
        return cust.get("email") or None
    except Exception:
        return None


# ─────────────────────────────────────────────
# Config / Price ID マッピング
# ─────────────────────────────────────────────

def load_all_configs() -> dict[str, dict]:
    """全製品の config.json を読み込む。key = project名"""
    configs = {}
    for fname in sorted(_CFG_DIR.glob("*.json")):
        proj = fname.stem
        with open(fname, encoding="utf-8") as f:
            configs[proj] = json.load(f)
    return configs


def build_price_to_product_map(configs: dict[str, dict]) -> dict[str, tuple[str, str]]:
    """
    price_id → (project_name, plan_key) のマップを構築。
    config に stripe_standard_price_id / stripe_pro_price_id がない場合、
    Stripe API の価格一覧から製品名で逆引きする。
    """
    price_map: dict[str, tuple[str, str]] = {}

    for proj, cfg in configs.items():
        product_name = cfg.get("product_name", proj)

        # 1. config に price_id が直書きされている場合
        std_price_id = cfg.get("stripe_standard_price_id")
        pro_price_id = cfg.get("stripe_pro_price_id")

        # 2. なければ stripe_standard_url / stripe_pro_url から payment_link 経由で逆引き
        if not std_price_id:
            std_url = cfg.get("stripe_standard_url", "")
            pro_url = cfg.get("stripe_pro_url", "")
            if std_url or pro_url:
                std_price_id, pro_price_id = _resolve_price_ids_from_links(std_url, pro_url)

        # 3. それでもなければ Stripe の価格一覧から製品名で検索
        if not std_price_id:
            std_price_id, pro_price_id = _find_price_ids_by_product_name(product_name)

        if std_price_id:
            price_map[std_price_id] = (proj, "standard")
        if pro_price_id:
            price_map[pro_price_id] = (proj, "pro")

    return price_map


def _resolve_price_ids_from_links(std_url: str, pro_url: str) -> tuple[str | None, str | None]:
    """Payment Link URL から price_id を取得。"""
    std_price_id = None
    pro_price_id = None
    try:
        for url, target in [(std_url, "std"), (pro_url, "pro")]:
            if not url:
                continue
            # payment_links/{id} の id を URL から抽出
            link_id = url.rstrip("/").split("/")[-1]
            items = _stripe_req("GET", f"payment_links/{link_id}/line_items")
            for item in items.get("data", []):
                price_id = item.get("price", {}).get("id")
                if price_id:
                    if target == "std":
                        std_price_id = price_id
                    else:
                        pro_price_id = price_id
    except Exception as e:
        print(f"  [WARN] payment link からの price_id 逆引き失敗: {e}")
    return std_price_id, pro_price_id


def _find_price_ids_by_product_name(product_name: str) -> tuple[str | None, str | None]:
    """Stripe の product 一覧から name で検索して price_id を返す。"""
    std_price_id = None
    pro_price_id = None
    try:
        products = _stripe_req("GET", "products?active=true&limit=100")
        target_prod_id = None
        for p in products.get("data", []):
            if p.get("name", "").lower() == product_name.lower():
                target_prod_id = p["id"]
                break
        if not target_prod_id:
            return None, None
        prices = _stripe_req("GET", f"prices?product={target_prod_id}&active=true&limit=10")
        for price in prices.get("data", []):
            amount = price.get("unit_amount", 0)
            if amount == 8980:
                std_price_id = price["id"]
            elif amount == 19800:
                pro_price_id = price["id"]
    except Exception as e:
        print(f"  [WARN] product name '{product_name}' からの price_id 検索失敗: {e}")
    return std_price_id, pro_price_id


# ─────────────────────────────────────────────
# 送信済み記録
# ─────────────────────────────────────────────

def load_sent_subscriptions() -> set[str]:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not _STATE_FILE.exists():
        return set()
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return set(data.get("sent_ids", []))
    except Exception:
        return set()


def save_sent_subscription(sub_id: str) -> None:
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    sent = load_sent_subscriptions()
    sent.add(sub_id)
    _STATE_FILE.write_text(
        json.dumps({"sent_ids": sorted(sent)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ─────────────────────────────────────────────
# Supabase
# ─────────────────────────────────────────────

def _supabase_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_ANON_KEY"]
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def insert_code_to_supabase(project: str, code: str, plan: str) -> bool:
    """Supabase の {project}_codes テーブルにアクセスコードを INSERT。"""
    url = os.environ["SUPABASE_URL"].rstrip("/")
    table = f"{project}_codes"
    endpoint = f"{url}/rest/v1/{table}"
    payload = json.dumps({"code": code, "plan": plan, "active": True}).encode("utf-8")
    headers = _supabase_headers()
    headers["Prefer"] = "return=minimal"
    req = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  [ERROR] Supabase INSERT 失敗 ({e.code}): {body}")
        return False


# ─────────────────────────────────────────────
# Gmail メール送信
# ─────────────────────────────────────────────

def send_code_email(
    to_email: str,
    project: str,
    product_name: str,
    app_url: str,
    plan: str,
    code: str,
) -> bool:
    """アクセスコードをメール送信する。"""
    gmail = os.environ["GMAIL_ADDRESS"]
    pwd = os.environ["GMAIL_APP_PASSWORD"]
    plan_label = PLAN_LABELS.get(plan, plan)
    limit = f"{PLAN_LIMITS.get(plan, '?')}件"
    price = PLAN_PRICES.get(plan, "")

    body = (
        f"この度は{product_name} {plan_label}プランにお申し込みいただき、誠にありがとうございます。\n\n"
        f"アクセスコードをお送りします。\n\n"
        f"■ アクセスコード\n{code}\n\n"
        f"■ ご利用開始の手順\n"
        f"1. {product_name}を開く\n"
        f"   {app_url}\n\n"
        f"2. メールアドレスを入力してログイン\n\n"
        f"3. 無料枠（5件）を使い切ると「アクセスコードを持っている方」欄が表示されます\n\n"
        f"4. 上記コードを入力 → {plan_label}プラン（月{limit}）が有効化されます\n\n"
        f"■ プラン内容\n"
        f"プラン: {plan_label}\n"
        f"月額: {price}\n"
        f"月間上限: {limit}\n\n"
        f"ご不明な点はお気軽にご返信ください。\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"TextSeries\n"
        f"Mail: {gmail}\n"
        f"Web: {app_url}\n"
        f"━━━━━━━━━━━━━━━━━━"
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"【{product_name}】{plan_label}プランのアクセスコードをお送りします"
    msg["From"] = gmail
    msg["To"] = to_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(gmail, pwd)
            smtp.send_message(msg)
        print(f"  [OK] メール送信成功: {to_email} / {product_name} {plan_label}")
        return True
    except Exception as e:
        print(f"  [ERROR] メール送信失敗: {e}")
        return False


# ─────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────

def process_project(project: str, configs: dict[str, dict], price_map: dict[str, tuple[str, str]]) -> int:
    """指定プロジェクトの新規課金をチェックしてコードを送信。返り値は送信件数。"""
    if project not in configs:
        print(f"[WARN] config が見つかりません: {project}")
        return 0

    cfg = configs[project]
    product_name = cfg.get("product_name", project)
    app_url = cfg.get("app_url", "")

    sent = 0
    sent_ids = load_sent_subscriptions()

    print(f"\n[{project}] サブスクリプションチェック中...")
    try:
        subscriptions = get_recent_subscriptions(hours=1)
    except Exception as e:
        print(f"  [ERROR] Stripe 取得失敗: {e}")
        return 0

    for sub in subscriptions:
        sub_id = sub["id"]

        if sub_id in sent_ids:
            continue  # 送信済み

        # price_id を取得
        items = sub.get("items", {}).get("data", [])
        if not items:
            continue
        price_id = items[0].get("price", {}).get("id")
        if not price_id:
            continue

        # この price_id が対象プロジェクトのものか確認
        mapping = price_map.get(price_id)
        if not mapping:
            continue
        mapped_project, plan = mapping
        if mapped_project != project:
            continue

        # customer email 取得
        customer = sub.get("customer")
        if isinstance(customer, dict):
            email = customer.get("email")
        else:
            email = get_customer_email(customer)

        if not email:
            print(f"  [WARN] email 取得失敗 (sub_id={sub_id})")
            continue

        print(f"  新規課金検出: {email} / {product_name} {PLAN_LABELS.get(plan, plan)}")

        # アクセスコード生成
        code = str(uuid.uuid4())

        # Supabase に INSERT
        if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_ANON_KEY"):
            if not insert_code_to_supabase(project, code, plan):
                print(f"  [WARN] Supabase INSERT 失敗。メール送信は続行します。")

        # メール送信
        if send_code_email(email, project, product_name, app_url, plan, code):
            save_sent_subscription(sub_id)
            sent += 1
        else:
            print(f"  [WARN] メール送信失敗。sub_id={sub_id} は未送信のまま残します。")

    if sent == 0:
        print(f"  新規課金なし")

    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Stripe新規課金チェック→コード自動送信")
    parser.add_argument("--project", help="対象プロジェクト名（省略で全製品）")
    args = parser.parse_args()

    # 必須環境変数チェック
    for var in ["STRIPE_SECRET_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"]:
        if not os.environ.get(var):
            print(f"[ERROR] 環境変数 {var} が設定されていません")
            sys.exit(1)

    configs = load_all_configs()

    print("Stripe price_id マップを構築中...")
    price_map = build_price_to_product_map(configs)
    print(f"  {len(price_map)} 件の price_id を登録")

    targets = [args.project] if args.project else ALL_PRODUCTS
    total_sent = 0
    for proj in targets:
        sent = process_project(proj, configs, price_map)
        total_sent += sent

    print(f"\n完了: 合計 {total_sent} 件のコードを送信しました")


if __name__ == "__main__":
    main()
