#!/usr/bin/env python3
"""
deploy_cloudrun.py — TextSeries製品をGoogle Cloud Runに一括デプロイ

使い方:
  python shared/gtm/scripts/deploy_cloudrun.py --all
  python shared/gtm/scripts/deploy_cloudrun.py --slug caretext
  python shared/gtm/scripts/deploy_cloudrun.py --all --dry-run
  python shared/gtm/scripts/deploy_cloudrun.py --slug caretext --min-instances 1
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

GCLOUD          = r"C:\Users\ryuuM\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
AI_HOLDINGS     = Path("C:/Users/ryuuM/ai-holdings")
FUDOTEXT        = Path("C:/Users/ryuuM/fudotext")
POOLS_JSON      = AI_HOLDINGS / "shared/gtm/config/gcp_pools.json"
REGION          = "asia-northeast1"
HOSTING_PROJECT = "textseries-tokutext-api"   # 課金有効・全サービスをここにデプロイ
HOSTING_ACCOUNT = "ryuumg03@gmail.com"

SLUG_DIR_MAP = {
    "kentext":  "kensetsu",
    "fudotext": "fudosan-copy",
}

def _load_env():
    env_path = AI_HOLDINGS / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if v and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()

_load_env()
SUPABASE_URL      = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SVC_KEY  = os.environ.get("SUPABASE_SERVICE_KEY", "")


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


def load_pools() -> dict:
    """slug -> {project_id, account, api_key} のマップを返す"""
    data = json.loads(POOLS_JSON.read_text(encoding="utf-8"))
    result = {}
    for pool in data["pools"]:
        individual = pool.get("individual_keys", {})
        for slug in pool["products"]:
            result[slug] = {
                "project_id": pool["project_id"],
                "account":    pool["account"],
                "api_key":    individual.get(slug, pool["api_key"]),
            }
    return result


def make_dockerfile() -> str:
    return """\
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt --no-cache-dir
COPY . .
RUN mkdir -p /app/.streamlit
EXPOSE 7860
ENV STREAMLIT_SERVER_PORT=7860
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0"]
"""


_SECRETS_OLD = (
    'if "GEMINI_API_KEY" in st.secrets:\n'
    '    os.environ["GEMINI_API_KEY"] = st.secrets["GEMINI_API_KEY"]\n'
    '    os.environ["SUPABASE_URL"] = st.secrets.get("SUPABASE_URL", "")\n'
    '    os.environ["SUPABASE_ANON_KEY"] = st.secrets.get("SUPABASE_ANON_KEY", "")\n'
    'else:\n'
    '    from dotenv import load_dotenv\n'
    '    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "../../../../.env"))'
)
_SECRETS_NEW = (
    'try:\n'
    '    if "GEMINI_API_KEY" in st.secrets:\n'
    '        os.environ.setdefault("GEMINI_API_KEY", st.secrets["GEMINI_API_KEY"])\n'
    '        os.environ.setdefault("SUPABASE_URL", st.secrets.get("SUPABASE_URL", ""))\n'
    '        os.environ.setdefault("SUPABASE_ANON_KEY", st.secrets.get("SUPABASE_ANON_KEY", ""))\n'
    'except Exception:\n'
    '    pass'
)


def patch_app_py(content: str, slug: str) -> str:
    """st.secrets への参照を os.environ に差し替え（Cloud Run は env var のみ）"""
    upper = slug.upper()

    # STRIPE URL: st.secrets.get → os.environ.get
    for suffix in ("STRIPE_STANDARD_URL", "STRIPE_PRO_URL"):
        key = f"{upper}_{suffix}"
        content = content.replace(
            f'st.secrets.get("{key}", "")',
            f'os.environ.get("{key}", "")',
        )

    # secrets loading ブロックをまるごと置換
    content = content.replace(_SECRETS_OLD, _SECRETS_NEW)
    return content


def enable_apis(project_id: str, account: str):
    """Cloud Run / Cloud Build / Artifact Registry を有効化"""
    apis = [
        "run.googleapis.com",
        "cloudbuild.googleapis.com",
        "artifactregistry.googleapis.com",
    ]
    for api in apis:
        subprocess.run(
            [GCLOUD, "services", "enable", api,
             f"--project={project_id}", f"--account={account}", "--quiet"],
            capture_output=True, text=True,
        )


def deploy_product(slug: str, pool_map: dict, registry: dict,
                   min_instances: int = 0, dry_run: bool = False) -> bool:
    pool    = pool_map.get(slug)
    if not pool:
        print(f"  ❌ {slug}: プール割り当てなし")
        return False

    # Geminiキーはプールから、デプロイ先は課金済みの集約プロジェクト
    project_id = HOSTING_PROJECT
    account    = HOSTING_ACCOUNT
    gemini_key = pool["api_key"]
    cfg        = load_config(slug)
    meta       = registry.get(slug, {})

    product_name = cfg.get("product_name") or slug.capitalize()
    src_dir      = SLUG_DIR_MAP.get(slug, slug)
    src          = FUDOTEXT / "saas-dev/projects" / src_dir

    print(f"\n🚀 {product_name}  →  {project_id} / {slug}")

    if not src.exists():
        print(f"  ❌ {src} が見つかりません")
        return False

    env_vars = {
        "GEMINI_API_KEY":                       gemini_key,
        "SUPABASE_URL":                         SUPABASE_URL,
        "SUPABASE_ANON_KEY":                    SUPABASE_ANON_KEY,
        "SUPABASE_SERVICE_KEY":                 SUPABASE_SVC_KEY,
        f"{slug.upper()}_STRIPE_STANDARD_URL":  cfg.get("stripe_standard_url", ""),
        f"{slug.upper()}_STRIPE_PRO_URL":       cfg.get("stripe_pro_url", ""),
    }
    env_str = ",".join(f"{k}={v}" for k, v in env_vars.items() if v)

    if dry_run:
        print(f"  [dry-run] gcloud run deploy {slug}")
        print(f"  [dry-run] project={project_id}  region={REGION}")
        print(f"  [dry-run] env vars: {list(env_vars.keys())}")
        return True

    # API有効化（初回のみ時間がかかる）
    enable_apis(project_id, account)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        app_src = (src / "app.py").read_text(encoding="utf-8")
        (tmp / "app.py").write_text(patch_app_py(app_src, slug), encoding="utf-8")

        for fname in ["gen.py", "db.py"]:
            if (src / fname).exists():
                shutil.copy(src / fname, tmp / fname)

        # requirements.txt がなければ標準セットを生成
        req_src = src / "requirements.txt"
        if req_src.exists():
            shutil.copy(req_src, tmp / "requirements.txt")
        else:
            (tmp / "requirements.txt").write_text(
                "streamlit>=1.32\npython-dotenv>=1.0\n", encoding="utf-8"
            )

        # 空の secrets.toml を置く（st.secrets アクセスエラーを防ぐ）
        (tmp / ".streamlit").mkdir(exist_ok=True)
        (tmp / ".streamlit" / "secrets.toml").write_text("", encoding="utf-8")

        (tmp / "Dockerfile").write_text(make_dockerfile(), encoding="utf-8")

        cmd = [
            GCLOUD, "run", "deploy", slug,
            "--source", str(tmp),
            f"--project={project_id}",
            f"--account={account}",
            f"--region={REGION}",
            "--allow-unauthenticated",
            "--port=7860",
            "--memory=512Mi",
            "--cpu=1",
            f"--min-instances={min_instances}",
            "--max-instances=10",
            "--timeout=300",
            "--quiet",
        ]
        if env_str:
            cmd += ["--set-env-vars", env_str]

        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)

        if r.returncode != 0:
            print(f"  ❌ デプロイ失敗:\n{r.stderr[-500:]}")
            return False

    # デプロイ済みURLを取得
    r2 = subprocess.run(
        [GCLOUD, "run", "services", "describe", slug,
         f"--project={project_id}", f"--account={account}",
         f"--region={REGION}", "--format=value(status.url)"],
        capture_output=True, text=True, encoding="utf-8",
    )
    url = r2.stdout.strip()
    print(f"  ✓ デプロイ完了: {url}")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug",          help="特定製品のみ")
    parser.add_argument("--all",           action="store_true", help="全製品")
    parser.add_argument("--dry-run",       action="store_true")
    parser.add_argument("--min-instances", type=int, default=0,
                        help="最小インスタンス数（0=スケールtoゼロ, 1=常時起動）")
    args = parser.parse_args()

    registry = load_registry()
    pool_map = load_pools()

    if args.all:
        slugs = list(pool_map.keys())
    elif args.slug:
        slugs = [args.slug]
    else:
        parser.print_help()
        sys.exit(1)

    success, failed = 0, []
    for slug in slugs:
        try:
            if deploy_product(slug, pool_map, registry,
                              min_instances=args.min_instances,
                              dry_run=args.dry_run):
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
