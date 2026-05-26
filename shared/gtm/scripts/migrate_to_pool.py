#!/usr/bin/env python3
"""
migrate_to_pool.py — 既存製品の壊れたGemini APIキーをプール方式に移行

壊れたキーを持つ製品を gcp_pools.json のプールにアサインし、
config JSONの gemini_api_key を更新する。

使い方:
  python shared/gtm/scripts/migrate_to_pool.py           # 自動検出・修正
  python shared/gtm/scripts/migrate_to_pool.py --dry-run # 変更せず確認のみ
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

AI_HOLDINGS = Path("C:/Users/ryuuM/ai-holdings")
CFG_DIR     = AI_HOLDINGS / "shared/gtm/config"
POOLS_JSON  = CFG_DIR / "gcp_pools.json"

GCLOUD_CMD  = r"C:\Users\ryuuM\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
POOL_ACCOUNTS = [
    "zhenbinglongsheng@gmail.com",
    "longshengzhenbing07@gmail.com",
]
PROJECT_CAP      = 10
PRODUCTS_PER_POOL = 5

# 漏洩・無効と判明しているキー
BAD_KEYS = {
    "AIzaSyBGHxbXZuvyZSjRVsH1LFr8QQ5QKYtZjLI",  # 最初の無効キー
    "AIzaSyBEYO6UnCWpbJk8nBRY1ID49rEa08TKltE",  # 漏洩キー
}


def _run(*args, account: str = None, timeout: int = 120) -> tuple[int, str]:
    cmd = [GCLOUD_CMD, *args]
    if account:
        cmd.append(f"--account={account}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def _project_count(account: str) -> int:
    rc, out = _run("projects", "list", "--format=value(projectId)", account=account)
    return len([p for p in out.splitlines() if p.strip()])


def _create_pool_project(pool_id: str, account: str) -> str:
    print(f"  新規プール [{pool_id}] を {account} で作成中...")
    rc, out = _run("projects", "create", pool_id, f"--name={pool_id}", "--quiet",
                   account=account)
    if rc != 0:
        if "already in use" in out or "already exists" in out:
            print(f"  プロジェクトは既に存在します。既存プロジェクトを再利用...")
        else:
            print(f"  プロジェクト作成失敗: {out[:200]}")
            return ""

    # account を指定して番号を取得
    _, num_out = _run("projects", "describe", pool_id, "--format=value(projectNumber)",
                      account=account)
    project_num = num_out.strip()
    if not project_num:
        print(f"  プロジェクト番号取得失敗")
        return ""

    print(f"  Gemini API を有効化中 (project={project_num})...")
    rc, out = _run("services", "enable", "generativelanguage.googleapis.com",
                   f"--project={project_num}", account=account)
    if rc != 0:
        print(f"  API有効化失敗: {out[:200]}")
        return ""

    rc2, before_out = _run("services", "api-keys", "list",
                           f"--project={project_num}", "--format=value(name)", account=account)
    before = set(l for l in before_out.splitlines() if l.strip())

    # 既存キーがあればそのまま返す
    if before:
        _, ks_out = _run("services", "api-keys", "get-key-string",
                         list(before)[0], "--format=value(keyString)", account=account)
        key_string = ks_out.strip()
        if key_string and key_string.startswith("AIzaSy"):
            print(f"  既存キーを再利用: {key_string[:20]}...")
            return key_string

    _run("services", "api-keys", "create",
         f"--project={project_num}", "--display-name=textseries-pool",
         "--quiet", account=account)

    for _ in range(6):
        time.sleep(5)
        rc, out = _run("services", "api-keys", "list",
                       f"--project={project_num}", "--format=value(name)", account=account)
        after = set(l for l in out.splitlines() if l.strip())
        new_keys = after - before
        if new_keys:
            _, ks_out = _run("services", "api-keys", "get-key-string",
                             list(new_keys)[0], "--format=value(keyString)", account=account)
            key_string = ks_out.strip()
            if key_string:
                print(f"  → {key_string[:20]}...")
                return key_string

    print(f"  キー取得タイムアウト")
    return ""


def assign_to_pool(slug: str, dry_run: bool) -> str:
    """slug をプールにアサインして APIキーを返す。"""
    pools_data = json.loads(POOLS_JSON.read_text(encoding="utf-8"))
    pools: list = pools_data.get("pools", [])

    # 既にアサイン済み
    for pool in pools:
        if slug in pool.get("products", []):
            key = pool.get("api_key", "")
            if key and key not in BAD_KEYS:
                print(f"  [{slug}] 既存プール {pool['project_id']} を再利用")
                return key

    # 空きのあるプールを探す
    for pool in pools:
        if len(pool.get("products", [])) < PRODUCTS_PER_POOL:
            if not dry_run:
                if slug not in pool["products"]:
                    pool["products"].append(slug)
                POOLS_JSON.write_text(
                    json.dumps(pools_data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            print(f"  [{slug}] プール {pool['project_id']} にアサイン (dry={dry_run})")
            return pool.get("api_key", "")

    # 新規プール作成
    pool_num = len(pools) + 1
    pool_prefix = pools_data.get("pool_prefix", "textseries-pool-")
    pool_id = f"{pool_prefix}{pool_num:03d}"

    chosen_account = ""
    for account in POOL_ACCOUNTS:
        count = _project_count(account)
        print(f"  {account}: {count}/{PROJECT_CAP} プロジェクト")
        if count < PROJECT_CAP:
            chosen_account = account
            break

    if not chosen_account:
        print(f"  ⚠️  全アカウントがプロジェクト上限")
        return ""

    if dry_run:
        print(f"  [{slug}] 新規プール {pool_id} ({chosen_account}) を作成予定 (dry-run)")
        return "DRY_RUN_KEY"

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
    POOLS_JSON.write_text(
        json.dumps(pools_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return api_key


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # 壊れたキーを持つ製品を探す
    bad_products = []
    for cfg_path in sorted(CFG_DIR.glob("*.json")):
        if cfg_path.name in ("gcp_pools.json",):
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        key = cfg.get("gemini_api_key", "")
        if not key or key in BAD_KEYS:
            slug = cfg_path.stem
            bad_products.append((slug, cfg_path, cfg))

    print(f"🔍 修正対象: {len(bad_products)} 製品")
    for slug, _, _ in bad_products:
        print(f"  - {slug}")

    if not bad_products:
        print("✅ 修正不要")
        return

    fixed = 0
    for slug, cfg_path, cfg in bad_products:
        print(f"\n{'─'*40}")
        print(f"🔧 {slug}")
        new_key = assign_to_pool(slug, args.dry_run)
        if not new_key or new_key == "DRY_RUN_KEY":
            print(f"  ⚠️  キー取得失敗 → スキップ")
            continue
        if not args.dry_run:
            cfg["gemini_api_key"] = new_key
            cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  ✅ config JSON 更新済み → {new_key[:20]}...")
        fixed += 1

    print(f"\n{'='*50}")
    print(f"{'[dry-run] ' if args.dry_run else ''}修正完了: {fixed}/{len(bad_products)} 製品")


if __name__ == "__main__":
    main()
