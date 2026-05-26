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
import re
import subprocess
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


def _find_existing_product(name: str, api_key: str) -> str | None:
    result = _req("GET", f"products?limit=100&active=true", None, api_key)
    for p in result.get("data", []):
        if p.get("name") == name:
            return p["id"]
    return None


def _find_active_payment_link(price_id: str, api_key: str) -> str | None:
    result = _req("GET", f"payment_links?limit=100&active=true", None, api_key)
    for link in result.get("data", []):
        items = _req("GET", f"payment_links/{link['id']}/line_items", None, api_key)
        for item in items.get("data", []):
            if item.get("price", {}).get("id") == price_id:
                return link["url"]
    return None


def _find_existing_price(product_id: str, amount: int, api_key: str) -> str | None:
    result = _req("GET", f"prices?product={product_id}&active=true&limit=10", None, api_key)
    for p in result.get("data", []):
        if p.get("unit_amount") == amount and p.get("recurring", {}).get("interval") == "month":
            return p["id"]
    return None


def create_product(name: str, description: str, api_key: str) -> str:
    existing = _find_existing_product(name, api_key)
    if existing:
        print(f"    既存のProductを再利用: {existing}")
        return existing
    result = _req("POST", "products", {"name": name, "description": description}, api_key)
    return result["id"]


def create_price(product_id: str, amount: int, api_key: str) -> str:
    existing = _find_existing_price(product_id, amount, api_key)
    if existing:
        print(f"    既存のPriceを再利用: {existing}")
        return existing
    result = _req("POST", "prices", {
        "product": product_id,
        "unit_amount": amount,
        "currency": "jpy",
        "recurring[interval]": "month",
    }, api_key)
    return result["id"]


def create_payment_link(price_id: str, api_key: str) -> str:
    existing = _find_active_payment_link(price_id, api_key)
    if existing:
        print(f"    既存のPayment Linkを再利用: {existing}")
        return existing
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


_GCLOUD_CMD = r"C:\Users\ryuuM\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
_POOLS_JSON = _CFG_DIR / "gcp_pools.json"

# APIキー専用アカウント（表に出さない）
_POOL_ACCOUNTS = [
    "zhenbinglongsheng@gmail.com",
    "longshengzhenbing07@gmail.com",
]
_PROJECT_CAP = 10


def _gcloud(*args: str, account: str = None, timeout: int = 120) -> tuple[int, str]:
    cmd = [_GCLOUD_CMD, *args]
    if account:
        cmd.append(f"--account={account}")
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    return result.returncode, result.stdout + result.stderr


def _gcloud_project_count(account: str) -> int:
    rc, out = _gcloud("projects", "list", "--format=value(projectId)", account=account)
    return len([p for p in out.splitlines() if p.strip()])


def _create_pool_project(pool_id: str, account: str) -> str:
    """プールプロジェクトを新規作成し Gemini APIキーを返す。"""
    import time

    print(f"  プールプロジェクト [{pool_id}] を {account} で作成中...")
    rc, out = _gcloud("projects", "create", pool_id, f"--name={pool_id}", "--quiet",
                      account=account)
    if rc != 0:
        if "already in use" in out or "already exists" in out:
            print(f"  プロジェクトは既に存在します。既存プロジェクトを再利用...")
        else:
            print(f"  プロジェクト作成失敗: {out[:200]}")
            return ""

    _, num_out = _gcloud("projects", "describe", pool_id, "--format=value(projectNumber)",
                         account=account)
    project_num = num_out.strip()
    if not project_num:
        print(f"  プロジェクト番号取得失敗")
        return ""

    print(f"  Gemini API を有効化中...")
    rc, out = _gcloud("services", "enable", "generativelanguage.googleapis.com",
                      f"--project={project_num}", account=account)
    if rc != 0:
        print(f"  API有効化失敗: {out[:200]}")
        return ""

    print(f"  APIキーを発行中...")
    before_rc, before_out = _gcloud(
        "services", "api-keys", "list",
        f"--project={project_num}", "--format=value(name)", account=account,
    )
    before = set(l for l in before_out.splitlines() if l.strip())

    # 既存キーがあれば再利用
    if before:
        _, ks_out = _gcloud(
            "services", "api-keys", "get-key-string",
            list(before)[0], "--format=value(keyString)", account=account,
        )
        ks = ks_out.strip()
        if ks and ks.startswith("AIzaSy"):
            print(f"  既存キーを再利用: {ks[:20]}...")
            return ks

    _gcloud(
        "services", "api-keys", "create",
        f"--project={project_num}",
        f"--display-name=textseries-pool",
        "--quiet", account=account,
    )

    key_string = ""
    for _ in range(6):
        time.sleep(5)
        rc, out = _gcloud(
            "services", "api-keys", "list",
            f"--project={project_num}", "--format=value(name)", account=account,
        )
        after = set(l for l in out.splitlines() if l.strip())
        new_keys = after - before
        if new_keys:
            _, ks_out = _gcloud(
                "services", "api-keys", "get-key-string",
                list(new_keys)[0], "--format=value(keyString)", account=account,
            )
            key_string = ks_out.strip()
            break

    if not key_string:
        print(f"  キー取得失敗")
        return ""
    print(f"  → 完了: {key_string[:20]}...")
    return key_string


def get_pool_gemini_key(slug: str) -> str:
    """
    slug をプールプロジェクトにアサインし Gemini APIキーを返す。
    プールは 5製品/プロジェクト。満杯なら新規プールを作成する。
    """
    pools_data = json.loads(_POOLS_JSON.read_text(encoding="utf-8"))
    products_per_pool: int = pools_data.get("products_per_pool", 5)
    pool_prefix: str = pools_data.get("pool_prefix", "textseries-pool-")
    pools: list = pools_data.get("pools", [])

    # 既にアサイン済みなら返す
    for pool in pools:
        if slug in pool.get("products", []):
            key = pool.get("api_key", "")
            if key:
                print(f"  既存プール [{pool['project_id']}] のキーを使用")
                return key

    # 空きのあるプールを探す
    for pool in pools:
        if len(pool.get("products", [])) < products_per_pool:
            pool["products"].append(slug)
            _POOLS_JSON.write_text(
                json.dumps(pools_data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  既存プール [{pool['project_id']}] に {slug} をアサイン")
            return pool.get("api_key", "")

    # 新しいプールを作成
    pool_num = len(pools) + 1
    pool_id = f"{pool_prefix}{pool_num:03d}"

    chosen_account = ""
    for account in _POOL_ACCOUNTS:
        count = _gcloud_project_count(account)
        if count < _PROJECT_CAP:
            chosen_account = account
            break

    if not chosen_account:
        print(f"  ⚠️  全APIアカウントがプロジェクト上限。.env のキーにフォールバック")
        return ""

    api_key = _create_pool_project(pool_id, chosen_account)
    if not api_key:
        return ""

    new_pool = {
        "project_id": pool_id,
        "account": chosen_account,
        "api_key": api_key,
        "products": [slug],
    }
    pools.append(new_pool)
    pools_data["pools"] = pools
    _POOLS_JSON.write_text(
        json.dumps(pools_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  新規プール [{pool_id}] 作成 → {slug} をアサイン")
    return api_key


def run_supabase_sql(sql: str, access_token: str, project_ref: str) -> list[str]:
    """Supabase Management API でSQLを実行する。エラーリストを返す。"""
    url = f"https://api.supabase.com/v1/projects/{project_ref}/database/query"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": "setup-stripe/1.0",
    }
    errors = []
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    for stmt in statements:
        body = json.dumps({"query": stmt + ";"}).encode()
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                r.read()
        except urllib.error.HTTPError as e:
            msg = e.read().decode()
            errors.append(f"{stmt[:60]}... → {msg[:100]}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--emoji",    default="📄", help="ポートフォリオカード用絵文字")
    parser.add_argument("--industry", default="",   help="業種表示テキスト（省略時はconfig自動取得）")
    parser.add_argument("--docs",     default="",   help="書類説明テキスト（省略時はconfig自動取得）")
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

    project_upper  = args.project.upper()
    supabase_url   = os.environ.get("SUPABASE_URL", "")
    supabase_key   = os.environ.get("SUPABASE_ANON_KEY", "")
    service_key    = os.environ.get("SUPABASE_SERVICE_KEY", "")

    print(f"\nGemini APIキー（プール方式）を取得中...")
    gemini_key = get_pool_gemini_key(args.project)
    if not gemini_key:
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        print(f"  .env の GEMINI_API_KEY にフォールバック")

    history_cols = cfg.get("history_columns", ["doc_type text", "input_1 text", "input_2 text", "result text"])
    history_col_sql = "\n".join(f"  {col}," for col in history_cols)
    p = args.project
    sql_block = f"""CREATE TABLE IF NOT EXISTS {p}_trials (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  email text UNIQUE NOT NULL,
  count integer DEFAULT 0,
  plan text,
  created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS {p}_codes (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  code text UNIQUE NOT NULL,
  plan text NOT NULL,
  active boolean DEFAULT true,
  created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS {p}_history (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  email text NOT NULL,
{history_col_sql}
  created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS {p}_feedback (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  email text,
  category text,
  rating text NOT NULL,
  regen_count integer DEFAULT 0,
  reasons text,
  created_at timestamptz DEFAULT now()
);
ALTER TABLE {p}_trials ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all" ON {p}_trials;
DROP POLICY IF EXISTS "anon_insert" ON {p}_trials;
DROP POLICY IF EXISTS "anon_select" ON {p}_trials;
CREATE POLICY "anon_insert" ON {p}_trials FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "anon_select" ON {p}_trials FOR SELECT TO anon USING (true);
ALTER TABLE {p}_history ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all" ON {p}_history;
DROP POLICY IF EXISTS "anon_insert" ON {p}_history;
DROP POLICY IF EXISTS "anon_select" ON {p}_history;
CREATE POLICY "anon_insert" ON {p}_history FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "anon_select" ON {p}_history FOR SELECT TO anon USING (true);
ALTER TABLE {p}_codes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all" ON {p}_codes;
DROP POLICY IF EXISTS "anon_select" ON {p}_codes;
CREATE POLICY "anon_select" ON {p}_codes FOR SELECT TO anon USING (true);
ALTER TABLE {p}_feedback ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "anon_all" ON {p}_feedback;
DROP POLICY IF EXISTS "anon_insert" ON {p}_feedback;
DROP POLICY IF EXISTS "anon_select" ON {p}_feedback;
CREATE POLICY "anon_insert" ON {p}_feedback FOR INSERT TO anon WITH CHECK (true);
CREATE POLICY "anon_select" ON {p}_feedback FOR SELECT TO anon USING (true);"""

    q = '"'
    service_line = f'SUPABASE_SERVICE_KEY = {q}{service_key}{q}\n' if service_key and service_key != supabase_key else ""
    secrets_block = (
        f'GEMINI_API_KEY = {q}{gemini_key}{q}\n'
        f'SUPABASE_URL = {q}{supabase_url}{q}\n'
        f'SUPABASE_ANON_KEY = {q}{supabase_key}{q}\n'
        f'{service_line}'
        f'{project_upper}_STRIPE_STANDARD_URL = {q}{urls["standard"]}{q}\n'
        f'{project_upper}_STRIPE_PRO_URL = {q}{urls["pro"]}{q}'
    )

    # Supabase SQL 自動実行
    supabase_token = os.environ.get("SUPABASE_ACCESS_TOKEN", "")
    supabase_ref = supabase_url.split("//")[-1].split(".")[0] if supabase_url else ""
    sql_done = False
    if supabase_token and supabase_ref:
        print(f"\nSupabase にテーブルを自動作成中...")
        errs = run_supabase_sql(sql_block, supabase_token, supabase_ref)
        if errs:
            for e in errs:
                print(f"  ⚠️  {e}")
        else:
            print(f"  → 全テーブル作成完了")
            sql_done = True

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

    # config JSON に stripe URL を永続化（gemini_api_key はgcp_pools.jsonで管理するため書かない）
    cfg["stripe_standard_url"] = urls["standard"]
    cfg["stripe_pro_url"] = urls["pro"]
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f"  → config JSON に stripe URL を保存")

    # clipboard.txt に追記（上書きしない）
    clipboard_path = _ROOT / "clipboard.txt"
    sep = "━" * 40
    gist_line = f"  ✅ {gist_secret_name} = {gist_id}\n" if gist_id else f"  ⚠️  Gist作成失敗（手動で作成してください）\n"
    sql_section = (
        f"=== ✅ Supabase SQL 自動実行済み ===\n"
        if sql_done else
        f"=== (1) Supabase SQL Editor にペースト → Run ===\n\n{sql_block}\n\n"
    )
    block = (
        f"\n{sep}\n"
        f"# {product_name} → {args.project}.streamlit.app\n"
        f"{sep}\n\n"
        f"{sql_section}"
        f"\n=== {'(2)' if not sql_done else '(1)'} Streamlit Cloud → {args.project} → Settings → Secrets にペースト → Save ===\n\n"
        f"{secrets_block}\n\n"
        f"=== 自動完了済み ===\n"
        f"{gist_line}"
    )
    with open(clipboard_path, "a", encoding="utf-8") as f:
        f.write(block)
    print(f"\n完了。clipboard.txt に追記しました。")

    # ポートフォリオ自動更新
    update_script = Path(__file__).parent / "update_portfolio.py"
    cmd = [sys.executable, str(update_script), "--add", args.project, "--emoji", args.emoji]
    if args.industry:
        cmd += ["--industry", args.industry]
    if args.docs:
        cmd += ["--docs", args.docs]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(result.stdout.strip() or "(portfolio更新ログなし)")
    if result.returncode != 0:
        print(f"⚠️  portfolio更新エラー: {result.stderr[:200]}")


if __name__ == "__main__":
    main()
