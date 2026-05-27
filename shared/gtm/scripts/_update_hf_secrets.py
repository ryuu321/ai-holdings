#!/usr/bin/env python3
"""
gcp_pools.json の最新キーを HF Spaces Secrets に反映する。
ファイルのアップロードは行わず、Secrets の更新のみ。
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import argparse, json, os
from pathlib import Path

AI_HOLDINGS = Path("C:/Users/ryuuM/ai-holdings")
POOLS_JSON  = AI_HOLDINGS / "shared/gtm/config/gcp_pools.json"
HF_USERNAME = "ryu321"

def _load_env():
    env_path = AI_HOLDINGS / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if v and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()

_load_env()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pools", nargs="+",
                        default=["textseries-pool-001","textseries-pool-002",
                                 "textseries-pool-003","textseries-pool-004"],
                        help="更新対象のプールID")
    parser.add_argument("--hf-token", default=os.environ.get("HF_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.hf_token:
        print("HF_TOKEN が見つかりません")
        sys.exit(1)

    try:
        from huggingface_hub import HfApi
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "huggingface_hub", "-q"], check=True)
        from huggingface_hub import HfApi

    api = HfApi(token=args.hf_token)
    pools_data = json.loads(POOLS_JSON.read_text(encoding="utf-8"))

    target_pools = {p["project_id"]: p for p in pools_data["pools"]
                    if p["project_id"] in args.pools}

    if not target_pools:
        print("対象プールが見つかりません")
        sys.exit(1)

    total_ok, total_fail = 0, []
    for pool_id, pool in target_pools.items():
        gemini_key = pool["api_key"]
        print(f"\n[{pool_id}] キー: {gemini_key[:20]}...")
        for slug in pool["products"]:
            repo_id = f"{HF_USERNAME}/{slug}"
            if args.dry_run:
                print(f"  [dry-run] {repo_id} → GEMINI_API_KEY 更新")
                total_ok += 1
                continue
            try:
                api.add_space_secret(repo_id=repo_id, key="GEMINI_API_KEY", value=gemini_key)
                print(f"  ✓ {slug}")
                total_ok += 1
            except Exception as e:
                err = str(e)
                if "404" in err or "not found" in err.lower():
                    print(f"  ⚠️  {slug}: Space未作成 → スキップ")
                else:
                    print(f"  ✗ {slug}: {err}")
                    total_fail.append(slug)

    print(f"\n{'='*50}")
    print(f"✅ {total_ok} 件更新完了")
    if total_fail:
        print(f"❌ 失敗: {', '.join(total_fail)}")

if __name__ == "__main__":
    main()
