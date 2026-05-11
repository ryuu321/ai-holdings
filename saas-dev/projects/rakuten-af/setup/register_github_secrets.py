"""
GitHub Secrets 自動登録スクリプト（ブログID版）
実行: python setup/register_github_secrets.py

hatena_blogs.json を読み込んで HATENA_BLOG_N_ID をGitHub Secretsに一括登録。
HATENA_ID / HATENA_API_KEY は既存のSecretをそのまま使う。

必要: pip install PyNaCl requests
"""
import base64
import json
import os
import re
import sys
from pathlib import Path

import requests
from nacl import encoding, public

BLOGS_FILE = Path(__file__).parent / "hatena_blogs.json"
ENV_FILE   = Path(__file__).parent.parent.parent.parent.parent / ".env"

REPO = "ryuu321/ai-holdings"
GITHUB_API = "https://api.github.com"


def load_github_token() -> str:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("GITHUB_TOKEN="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("GITHUB_TOKEN", "")


def get_repo_public_key(token: str) -> tuple[str, str]:
    r = requests.get(
        f"{GITHUB_API}/repos/{REPO}/actions/secrets/public-key",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
    )
    r.raise_for_status()
    d = r.json()
    return d["key_id"], d["key"]


def encrypt_secret(public_key_b64: str, value: str) -> str:
    pk = public.PublicKey(public_key_b64.encode(), encoding.Base64Encoder())
    encrypted = public.SealedBox(pk).encrypt(value.encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def set_secret(token: str, key_id: str, pk: str, name: str, value: str):
    r = requests.put(
        f"{GITHUB_API}/repos/{REPO}/actions/secrets/{name}",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
        json={"encrypted_value": encrypt_secret(pk, value), "key_id": key_id},
    )
    status = "OK" if r.status_code in (201, 204) else f"NG({r.status_code})"
    print(f"  {status}: {name} = {value}")


def update_local_env(blogs: list):
    text = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    for blog in blogs:
        k = f"HATENA_BLOG_{blog['index']}_ID"
        v = blog["blog_id"]
        if k in text:
            text = re.sub(rf"^{k}=.*$", f"{k}={v}", text, flags=re.MULTILINE)
        else:
            text = text.rstrip() + f"\n{k}={v}\n"
    ENV_FILE.write_text(text, encoding="utf-8")
    print(".env を更新しました。")


def main():
    if not BLOGS_FILE.exists():
        print(f"[ERROR] {BLOGS_FILE} がありません。先に create_hatena_blogs.py を実行してください。")
        sys.exit(1)

    blogs = json.loads(BLOGS_FILE.read_text(encoding="utf-8"))
    if not blogs:
        print("[ERROR] blogs が空です。")
        sys.exit(1)

    token = load_github_token()
    if not token:
        print("[ERROR] GITHUB_TOKEN が .env に見つかりません。")
        sys.exit(1)

    print(f"GitHub Secrets 登録 → {REPO} ({len(blogs)}ブログ)")
    key_id, pk = get_repo_public_key(token)

    for blog in blogs:
        set_secret(token, key_id, pk, f"HATENA_BLOG_{blog['index']}_ID", blog["blog_id"])

    update_local_env(blogs)
    print(f"\n完了！ {len(blogs)}個のシークレットを登録しました。")
    print("次の GitHub Actions 実行から複数ブログに分散投稿されます。")


if __name__ == "__main__":
    main()
