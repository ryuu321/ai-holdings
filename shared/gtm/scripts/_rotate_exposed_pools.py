#!/usr/bin/env python3
"""pool-001〜004 の露出キーを強制削除・再発行し gcp_pools.json + config JSONs を更新する"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import json, subprocess, time
from pathlib import Path

GCLOUD      = r"C:\Users\ryuuM\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
AI_HOLDINGS = Path("C:/Users/ryuuM/ai-holdings")
POOLS_JSON  = AI_HOLDINGS / "shared/gtm/config/gcp_pools.json"
CFG_DIR     = AI_HOLDINGS / "shared/gtm/config"
EXPOSED     = {"textseries-pool-001","textseries-pool-002",
               "textseries-pool-003","textseries-pool-004"}

def _run(*args, account=None, timeout=120):
    cmd = [GCLOUD, *args]
    if account:
        cmd.append(f"--account={account}")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout + r.stderr

def rotate_pool(pool: dict) -> str:
    pid, acct = pool["project_id"], pool["account"]
    print(f"\n[{pid}]")

    _, num_out = _run("projects", "describe", pid,
                      "--format=value(projectNumber)", account=acct)
    proj_num = num_out.strip()
    if not proj_num:
        print("  番号取得失敗"); return ""

    rc, out = _run("services", "api-keys", "list",
                   f"--project={proj_num}", "--format=value(name)", account=acct)
    for kn in [k for k in out.splitlines() if k.strip()]:
        print(f"  削除: {kn.split('/')[-1]}")
        _run("services", "api-keys", "delete", kn, "--quiet", account=acct)

    time.sleep(5)
    _run("services", "api-keys", "create",
         f"--project={proj_num}", "--display-name=pool-renewed",
         "--quiet", account=acct)

    for _ in range(8):
        time.sleep(5)
        rc, out = _run("services", "api-keys", "list",
                       f"--project={proj_num}", "--format=value(name)", account=acct)
        new_keys = [k for k in out.splitlines() if k.strip()]
        if new_keys:
            _, ks = _run("services", "api-keys", "get-key-string",
                         new_keys[0], "--format=value(keyString)", account=acct)
            key = ks.strip()
            if key.startswith("AIzaSy"):
                print(f"  新キー: {key[:20]}...")
                return key
    print("  タイムアウト"); return ""

def main():
    pools_data = json.loads(POOLS_JSON.read_text(encoding="utf-8"))

    for pool in pools_data["pools"]:
        if pool["project_id"] not in EXPOSED:
            continue
        old_key = pool["api_key"]
        new_key = rotate_pool(pool)
        if not new_key:
            continue

        pool["api_key"] = new_key
        POOLS_JSON.write_text(
            json.dumps(pools_data, ensure_ascii=False, indent=2), encoding="utf-8")

        for slug in pool["products"]:
            cfg_path = CFG_DIR / f"{slug}.json"
            if not cfg_path.exists(): continue
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            if cfg.get("gemini_api_key") == old_key:
                cfg["gemini_api_key"] = new_key
                cfg_path.write_text(
                    json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  {slug}: config 更新")

    print("\n--- .env の露出プールキーを新キーに差替え ---")
    import re
    env_path = AI_HOLDINGS / ".env"
    text = env_path.read_text(encoding="utf-8")
    for pool in pools_data["pools"]:
        if pool["project_id"] not in EXPOSED: continue
        # 旧キーを特定するには再読が必要だが、ここでは全プールキーを確認して差替え
        # 新キーはすでに pool["api_key"] に入っている
        # 旧キーは commit に残っているが .env にはまだ旧キーのまま
    # 最も確実な方法: manage_gemini_keys.py を呼んで全textseries-* キーを再収集
    print("  manage_gemini_keys.py を実行して .env を再構築します...")
    subprocess.run([sys.executable,
                    str(AI_HOLDINGS / "shared/gtm/scripts/manage_gemini_keys.py")],
                   text=True, encoding="utf-8", errors="replace")

if __name__ == "__main__":
    main()
