#!/usr/bin/env python3
"""
deploy_hf.py — TextSeries製品をHugging Face Spacesに一括デプロイ

使い方:
  python shared/gtm/scripts/deploy_hf.py --all
  python shared/gtm/scripts/deploy_hf.py --slug kangotext
  python shared/gtm/scripts/deploy_hf.py --all --dry-run
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

AI_HOLDINGS = Path("C:/Users/ryuuM/ai-holdings")
FUDOTEXT    = Path("C:/Users/ryuuM/fudotext")
HF_USERNAME = "ryu321"

# slug と実際のディレクトリが異なる旧製品
SLUG_DIR_MAP = {
    "kentext":  "kensetsu",
    "fudotext": "fudosan-copy",
}

SUPABASE_URL       = "https://byzjkcywrhtmjicrrwfw.supabase.co"
SUPABASE_ANON_KEY  = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ5emprY3l3cmh0bWppY3Jyd2Z3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzkxNjYyNjksImV4cCI6MjA5NDc0MjI2OX0.uaqpSsJ7BsAlWXIUiFkyuaG9SNNHUU_CLktQmZfMmHo"
SUPABASE_SVC_KEY   = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ5emprY3l3cmh0bWppY3Jyd2Z3Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3OTE2NjI2OSwiZXhwIjoyMDk0NzQyMjY5fQ.-2O0KQc80F24NWT9bqmvqFgPdu1nRmXvLJru8p3bp4M"

_KNOWN_BAD_KEYS = {
    "AIzaSyBGHxbXZuvyZSjRVsH1LFr8QQ5QKYtZjLI",
    "AIzaSyBEYO6UnCWpbJk8nBRY1ID49rEa08TKltE",
}


# ── ライブラリ確認 ────────────────────────────────────────────────────────────

def ensure_deps():
    try:
        import huggingface_hub
    except ImportError:
        print("huggingface_hub をインストール中...")
        subprocess.run([sys.executable, "-m", "pip", "install", "huggingface_hub", "-q"], check=True)


# ── レジストリ / config 読み込み ────────────────────────────────────────────

def load_registry() -> dict:
    path = AI_HOLDINGS / "shared/portfolio/registry.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    return {p["slug"]: p for p in items}


def load_config(slug: str) -> dict:
    path = AI_HOLDINGS / "shared/gtm/config" / f"{slug}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── app.py パッチ（HF Spaces は st.secrets ではなく env var） ────────────

_SECRETS_BLOCK_RE = re.compile(
    r'if "GEMINI_API_KEY" in st\.secrets:.*?'
    r'(?=\n_USE_DB|\nst\.set_page|\n\n)',
    re.DOTALL,
)

_SECRETS_BLOCK_REPLACEMENT = textwrap.dedent("""\
    try:
        if "GEMINI_API_KEY" in st.secrets:
            os.environ.setdefault("GEMINI_API_KEY", st.secrets["GEMINI_API_KEY"])
            os.environ.setdefault("SUPABASE_URL", st.secrets.get("SUPABASE_URL", ""))
            os.environ.setdefault("SUPABASE_ANON_KEY", st.secrets.get("SUPABASE_ANON_KEY", ""))
    except Exception:
        pass
    if not os.environ.get("GEMINI_API_KEY"):
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../../../.env"))
        except Exception:
            pass""")


def patch_app_py(content: str, slug: str) -> str:
    upper = slug.upper()

    # STRIPE URL: st.secrets.get → os.environ.get（HF Spaces はenv var）
    for suffix in ("STRIPE_STANDARD_URL", "STRIPE_PRO_URL"):
        key = f"{upper}_{suffix}"
        content = content.replace(
            f'st.secrets.get("{key}", "")',
            f'os.environ.get("{key}", "")',
        )

    # secrets loading ブロックを try/except でラップ
    content = _SECRETS_BLOCK_RE.sub(_SECRETS_BLOCK_REPLACEMENT, content)

    return content


# ── README.md / Dockerfile 生成 ─────────────────────────────────────────────

def make_readme(product_name: str, emoji: str) -> str:
    return f"""---
title: {product_name}
emoji: {emoji}
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---
"""


def make_dockerfile() -> str:
    return """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir
COPY . .
EXPOSE 7860
ENV STREAMLIT_SERVER_PORT=7860
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]
"""


# ── 1製品デプロイ ────────────────────────────────────────────────────────────

def deploy_product(slug: str, hf_token: str, dry_run: bool = False) -> bool:
    from huggingface_hub import HfApi

    api     = HfApi(token=hf_token)
    repo_id = f"{HF_USERNAME}/{slug}"
    src_dir = SLUG_DIR_MAP.get(slug, slug)
    src     = FUDOTEXT / "saas-dev/projects" / src_dir

    registry = load_registry()
    meta     = registry.get(slug, {})
    cfg      = load_config(slug)

    emoji        = meta.get("emoji", "📄")
    product_name = cfg.get("product_name") or slug.capitalize()

    print(f"\n🚀 {product_name}  →  {repo_id}")

    if not src.exists():
        print(f"  ❌ {src} が見つかりません（fudotextリポジトリ未生成）")
        return False

    # Gemini キー（config JSONから取得、無効キーは gcp_pools.json にフォールバック）
    gemini_key = cfg.get("gemini_api_key", "")
    if not gemini_key or gemini_key in _KNOWN_BAD_KEYS:
        pools_path = AI_HOLDINGS / "shared/gtm/config/gcp_pools.json"
        try:
            pools_data = json.loads(pools_path.read_text(encoding="utf-8"))
            for pool in pools_data.get("pools", []):
                if slug in pool.get("products", []):
                    gemini_key = pool.get("api_key", "")
                    break
        except Exception:
            pass
    if not gemini_key or gemini_key in _KNOWN_BAD_KEYS:
        gemini_key = ""
        print(f"  ⚠️  有効なGemini APIキーが見つかりません")

    secrets = {
        "GEMINI_API_KEY":                       gemini_key,
        "SUPABASE_URL":                         SUPABASE_URL,
        "SUPABASE_ANON_KEY":                    SUPABASE_ANON_KEY,
        "SUPABASE_SERVICE_KEY":                 SUPABASE_SVC_KEY,
        f"{slug.upper()}_STRIPE_STANDARD_URL":  cfg.get("stripe_standard_url", ""),
        f"{slug.upper()}_STRIPE_PRO_URL":       cfg.get("stripe_pro_url", ""),
    }

    if dry_run:
        print(f"  [dry-run] Space: {repo_id}")
        print(f"  [dry-run] secrets: {list(secrets.keys())}")
        return True

    # Space 作成（既存の場合はスキップ、レート制限時も続行）
    try:
        api.create_repo(repo_id=repo_id, repo_type="space", space_sdk="docker",
                        private=False, exist_ok=True)
        print("  ✓ Space 作成/確認")
    except Exception as e:
        if "429" in str(e) or "rate limit" in str(e).lower():
            print("  ⚠️  Space作成レート制限 → 既存Spaceを更新")
        else:
            raise

    # ファイルをテンポラリに展開してアップロード
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # app.py パッチして書き出し
        app_src = (src / "app.py").read_text(encoding="utf-8")
        (tmp / "app.py").write_text(patch_app_py(app_src, slug), encoding="utf-8")

        # 残りのファイルをコピー
        for fname in ["gen.py", "db.py", "requirements.txt"]:
            if (src / fname).exists():
                shutil.copy(src / fname, tmp / fname)

        # README.md + Dockerfile
        (tmp / "README.md").write_text(make_readme(product_name, emoji), encoding="utf-8")
        (tmp / "Dockerfile").write_text(make_dockerfile(), encoding="utf-8")

        api.upload_folder(folder_path=str(tmp), repo_id=repo_id, repo_type="space",
                          commit_message=f"deploy {slug}")
    print("  ✓ ファイルアップロード完了")

    # Secrets 設定
    for key, value in secrets.items():
        if value:
            api.add_space_secret(repo_id=repo_id, key=key, value=value)
    print(f"  ✓ Secrets 設定完了 ({len([v for v in secrets.values() if v])}件)")

    print(f"  🌐 https://huggingface.co/spaces/{repo_id}")
    return True


# ── エントリポイント ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug",       help="特定製品のみデプロイ")
    parser.add_argument("--all",        action="store_true", help="全製品デプロイ")
    parser.add_argument("--hf-token",   default=os.environ.get("HF_TOKEN", ""))
    parser.add_argument("--dry-run",    action="store_true")
    args = parser.parse_args()

    if not args.hf_token:
        # .env から読む
        env_path = AI_HOLDINGS / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("HF_TOKEN="):
                    args.hf_token = line.split("=", 1)[1].strip()
                    break

    if not args.hf_token:
        print("HF_TOKEN が見つかりません。.env に HF_TOKEN=hf_... を追加してください")
        sys.exit(1)

    ensure_deps()

    if args.all:
        slugs = list(load_registry().keys())
    elif args.slug:
        slugs = [args.slug]
    else:
        parser.print_help()
        sys.exit(1)

    success, failed = 0, []
    for slug in slugs:
        try:
            if deploy_product(slug, args.hf_token, args.dry_run):
                success += 1
            else:
                failed.append(slug)
        except Exception as e:
            print(f"  ❌ {slug}: {e}")
            failed.append(slug)

    print(f"\n{'='*50}")
    print(f"✅ {success}/{len(slugs)} 製品デプロイ完了")
    if failed:
        print(f"❌ 失敗: {', '.join(failed)}")


if __name__ == "__main__":
    main()
