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
import sys
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CFG_DIR = _ROOT / "shared" / "gtm" / "config"

# .envを手動ロード（python-dotenv不要）
_env_file = _ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

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


def _gh_req(method: str, path: str, token: str, data: dict | None = None) -> dict:
    url = f"https://api.github.com{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            content = r.read()
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub API エラー ({e.code}): {e.read().decode()}") from None


def create_gist(project: str, token: str) -> str:
    filename = f"{project}_sent_log.csv"
    result = _gh_req("POST", "/gists", token, {
        "description": f"{project} sent_log (auto-created by setup_stripe.py)",
        "public": False,
        "files": {filename: {"content": "sent_at,email,replied"}},
    })
    return result["id"]


def set_github_secret(repo: str, secret_name: str, secret_value: str, token: str) -> None:
    # リポジトリの公開鍵を取得
    pub_key_data = _gh_req("GET", f"/repos/{repo}/actions/secrets/public-key", token)
    key_id = pub_key_data["key_id"]
    key_b64 = pub_key_data["key"]

    # libsodium で暗号化（PyNaClが必要）
    # PyNaClがない場合は gh CLI にフォールバック
    try:
        from base64 import b64decode, b64encode
        from nacl import encoding, public  # type: ignore
        pub_key = public.PublicKey(key_b64.encode(), encoding.Base64Encoder)
        box = public.SealedBox(pub_key)
        encrypted = b64encode(box.encrypt(secret_value.encode())).decode()
        _gh_req("PUT", f"/repos/{repo}/actions/secrets/{secret_name}", token, {
            "encrypted_value": encrypted,
            "key_id": key_id,
        })
    except ImportError:
        # PyNaClがない場合はgh CLIを使う
        import subprocess
        subprocess.run(
            ["gh", "secret", "set", secret_name, "--body", secret_value, "--repo", repo],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    args = parser.parse_args()

    api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not api_key:
        print("ERROR: STRIPE_SECRET_KEY が .env に設定されていません。")
        return

    cfg_path = _CFG_DIR / f"{args.project}.json"
    with open(cfg_path, encoding="utf-8-sig") as f:
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
    supabase_url  = os.environ.get("SUPABASE_URL", "")
    supabase_key  = os.environ.get("SUPABASE_ANON_KEY", "")
    gemini_key    = os.environ.get("GEMINI_API_KEY", "")

    sql_block = f"""CREATE TABLE {args.project}_feedback (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  email text,
  category text,
  rating text NOT NULL,
  regen_count integer DEFAULT 0,
  reasons text,
  created_at timestamptz DEFAULT now()
);
ALTER TABLE {args.project}_feedback ENABLE ROW LEVEL SECURITY;
CREATE POLICY "anon_all" ON {args.project}_feedback FOR ALL TO anon USING (true) WITH CHECK (true);"""

    q = '"'
    secrets_block = (
        f'GEMINI_API_KEY = {q}{gemini_key}{q}\n'
        f'SUPABASE_URL = {q}{supabase_url}{q}\n'
        f'SUPABASE_ANON_KEY = {q}{supabase_key}{q}\n'
        f'{project_upper}_STRIPE_STANDARD_URL = {q}{urls["standard"]}{q}\n'
        f'{project_upper}_STRIPE_PRO_URL = {q}{urls["pro"]}{q}'
    )

    # Gist作成 + GitHub Secrets登録
    gist_token  = os.environ.get("GIST_TOKEN", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    gist_secret_name = f"{project_upper}_SENT_LOG_GIST_ID"
    gist_id = ""

    if gist_token:
        print(f"\nGist を作成中...")
        try:
            gist_id = create_gist(args.project, gist_token)
            print(f"  → Gist ID: {gist_id}")
        except Exception as e:
            print(f"  Gist作成失敗: {e}")

    if gist_id and github_token:
        print(f"GitHub Secrets に {gist_secret_name} を登録中...")
        # GISTトークンとGITHUBトークンは同じリポジトリ用途で使用
        # repoはGITHUB_TOKENのスコープに依存するため環境変数から読む
        repo = os.environ.get("GITHUB_REPOSITORY", "ryuu321/ai-holdings")
        try:
            set_github_secret(repo, gist_secret_name, gist_id, github_token)
            print(f"  → {gist_secret_name} 登録完了")
        except Exception as e:
            print(f"  Secrets登録失敗（手動で登録してください）: {e}")

    clipboard_path = _ROOT / "clipboard.txt"
    gist_line = f"  ✅ {gist_secret_name} = {gist_id}\n" if gist_id else f"  ⚠️  Gist作成失敗（手動で作成してください）\n"
    clipboard_path.write_text(
        f"=== (1) Supabase SQL Editor にペースト → Run ===\n\n"
        f"{sql_block}\n\n"
        f"=== (2) Streamlit Cloud → {args.project} → Settings → Secrets にペースト → Save ===\n\n"
        f"{secrets_block}\n\n"
        f"=== 自動完了済み ===\n"
        f"{gist_line}",
        encoding="utf-8",
    )
    print(f"\n完了。clipboard.txt に SQL + Secrets の2点セットを出力しました。")


if __name__ == "__main__":
    main()
