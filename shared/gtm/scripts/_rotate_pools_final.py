#!/usr/bin/env python3
"""pool-001〜004 の現行キーを削除・再発行し gcp_pools.json を更新する（最終クリーンアップ）"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import json, subprocess, time
from pathlib import Path

GCLOUD     = r"C:\Users\ryuuM\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
POOLS_JSON = Path("C:/Users/ryuuM/ai-holdings/shared/gtm/config/gcp_pools.json")

def _run(*args, account=None, timeout=120):
    cmd = [GCLOUD, *args]
    if account:
        cmd.append(f"--account={account}")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout + r.stderr

def rotate_pool(pool: dict) -> str:
    pid, acct = pool["project_id"], pool["account"]
    print(f"\n[{pid}] 再発行中...")

    _, num_out = _run("projects", "describe", pid,
                      "--format=value(projectNumber)", account=acct)
    proj_num = num_out.strip()
    if not proj_num:
        print("  番号取得失敗"); return ""

    # 既存キーを全削除
    _, out = _run("services", "api-keys", "list",
                  f"--project={proj_num}", "--format=value(name)", account=acct)
    for kn in [k for k in out.splitlines() if k.strip()]:
        print(f"  削除: {kn.split('/')[-1]}")
        _run("services", "api-keys", "delete", kn, "--quiet", account=acct)

    time.sleep(5)
    # 新キー発行
    _run("services", "api-keys", "create",
         f"--project={proj_num}", "--display-name=pool-final",
         "--quiet", account=acct)

    # 新キーを取得（最大40秒待機）
    for _ in range(8):
        time.sleep(5)
        _, out = _run("services", "api-keys", "list",
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
    target_ids = {"textseries-pool-001", "textseries-pool-002",
                  "textseries-pool-003", "textseries-pool-004"}

    updated = 0
    for pool in pools_data["pools"]:
        if pool["project_id"] not in target_ids:
            continue
        new_key = rotate_pool(pool)
        if not new_key:
            print(f"  SKIP {pool['project_id']}: キー取得失敗")
            continue
        pool["api_key"] = new_key
        POOLS_JSON.write_text(
            json.dumps(pools_data, ensure_ascii=False, indent=2), encoding="utf-8")
        updated += 1
        print(f"  gcp_pools.json 更新済み: {pool['project_id']}")

    print(f"\n完了: {updated}/4 プール再発行")
    if updated == 4:
        print("pool-001〜004 の旧キー（git履歴に残っていたもの）は無効化されました")

if __name__ == "__main__":
    main()
