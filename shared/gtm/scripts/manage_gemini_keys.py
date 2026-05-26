#!/usr/bin/env python3
"""
manage_gemini_keys.py — Gemini APIキー自動管理

機能:
  - 全gcloudアカウントのGCPプロジェクトからキーを収集
  - 漏洩キー(403)を自動削除・同プロジェクトで再発行
  - .envのGEMINI_API_KEY, GEMINI_API_KEY_2... を自動更新
  - プロジェクト上限到達時に次のアカウントへ自動切替

使い方:
  python shared/gtm/scripts/manage_gemini_keys.py           # 確認・修復
  python shared/gtm/scripts/manage_gemini_keys.py --create  # 新規プロジェクト+キー追加
  python shared/gtm/scripts/manage_gemini_keys.py --status  # 現状表示のみ
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ENV_PATH    = Path("C:/Users/ryuuM/ai-holdings/.env")
PROJECT_CAP = 10   # GCPアカウントあたりの上限（無料枠）
GEMINI_API  = "generativelanguage.googleapis.com"

# Windows では gcloud.cmd を使う
import shutil as _shutil
GCLOUD = (
    _shutil.which("gcloud")
    or r"C:\Users\ryuuM\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
)


# ── gcloud ヘルパー ─────────────────────────────────────────────────────────

def _run(cmd: list, account: str = None) -> str:
    # gcloud → GCLOUD パスに置換
    cmd = [GCLOUD if c == "gcloud" else c for c in cmd]
    if account:
        cmd = cmd + [f"--account={account}"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip()


def list_accounts() -> list:
    out = _run(["gcloud", "auth", "list", "--format=value(account)"])
    return [a for a in out.splitlines() if a.strip()]


def list_projects(account: str) -> list:
    out = _run(["gcloud", "projects", "list", "--format=value(projectId)"], account)
    return [p for p in out.splitlines() if p.strip()]


def enable_gemini_api(project: str, account: str):
    _run(["gcloud", "services", "enable", GEMINI_API,
          f"--project={project}", "--quiet"], account)


def list_keys(project: str, account: str) -> list:
    """プロジェクト内の全APIキー名を返す"""
    out = _run(["gcloud", "services", "api-keys", "list",
                f"--project={project}", "--format=value(name)"], account)
    return [k for k in out.splitlines() if k.strip()]


def get_key_string(key_name: str, account: str) -> str:
    out = _run(["gcloud", "services", "api-keys", "get-key-string",
                key_name, "--format=value(keyString)"], account)
    return out.strip()


def delete_key(key_name: str, account: str):
    _run(["gcloud", "services", "api-keys", "delete", key_name, "--quiet"], account)


def create_key(project: str, account: str, display_name: str = "gemini-auto") -> str:
    """新規APIキーを作成してキー文字列を返す"""
    # 作成前のキー一覧を記録
    before = set(list_keys(project, account))

    _run(["gcloud", "services", "api-keys", "create",
          f"--project={project}",
          f"--display-name={display_name}", "--quiet"], account)

    # 最大30秒待って新しいキーが現れるまでリトライ
    for _ in range(6):
        time.sleep(5)
        after = set(list_keys(project, account))
        new_keys = after - before
        if new_keys:
            return get_key_string(list(new_keys)[0], account)
    return ""


def create_project(project_id: str, account: str) -> bool:
    r = subprocess.run(
        [GCLOUD, "projects", "create", project_id,
         "--name", project_id, f"--account={account}", "--quiet"],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode == 0


# ── Gemini キーテスト ────────────────────────────────────────────────────────

def test_key(api_key: str) -> str:
    """ok / leaked / quota / error を返す"""
    payload = json.dumps({
        "contents": [{"parts": [{"text": "hi"}]}],
        "generationConfig": {"maxOutputTokens": 10}
    }).encode()
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return "ok"
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        if e.code == 403 and "leaked" in body:
            return "leaked"
        if e.code in (429, 403):
            return "quota"
        return f"error_{e.code}"
    except Exception:
        return "error"


# ── .env 管理 ────────────────────────────────────────────────────────────────

def load_env() -> dict:
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if v:
                env[k.strip()] = v.strip()
    return env


def save_gemini_keys(valid_keys: list):
    """GEMINI_API_KEY, GEMINI_API_KEY_2... を .env に書き込む"""
    text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    lines = text.splitlines()

    # 既存のGEMINI_API_KEY行を全削除
    lines = [l for l in lines
             if not re.match(r"^GEMINI_API_KEY(_\d+)?=", l)]

    # 先頭に追加
    new_lines = []
    for i, key in enumerate(valid_keys):
        suffix = "" if i == 0 else f"_{i+1}"
        new_lines.append(f"GEMINI_API_KEY{suffix}={key}")

    ENV_PATH.write_text("\n".join(new_lines + lines) + "\n", encoding="utf-8")
    print(f"  ✅ .env 更新: {len(valid_keys)}個のキーを保存")


# ── メイン処理 ───────────────────────────────────────────────────────────────

def _is_textseries_project(project_id: str) -> bool:
    """TextSeriesのプロジェクトのみ対象にする（gen-lang-client-* などは除外）"""
    return project_id.startswith("textseries-")


def collect_all_keys() -> list:
    """TextSeriesプロジェクトのみからキー文字列を収集"""
    accounts = list_accounts()
    print(f"📋 gcloudアカウント: {accounts}")
    result = []  # [(account, project, key_name, key_string)]

    for account in accounts:
        all_projects = list_projects(account)
        projects = [p for p in all_projects if _is_textseries_project(p)]
        skipped = len(all_projects) - len(projects)
        print(f"\n👤 {account} → {len(projects)}プロジェクト（非TextSeries {skipped}件をスキップ）")
        for project in projects:
            keys = list_keys(project, account)
            for key_name in keys:
                ks = get_key_string(key_name, account)
                if ks and ks.startswith("AIzaSy"):
                    result.append((account, project, key_name, ks))

    return result


def repair_and_update(create_new: bool = False):
    all_keys = collect_all_keys()
    print(f"\n🔍 合計 {len(all_keys)} キーを発見 → テスト中...")

    valid   = []
    leaked  = []
    quota   = []

    for account, project, key_name, ks in all_keys:
        status = test_key(ks)
        label  = ks[:20] + "..."
        if status == "ok":
            print(f"  ✅ {label}  ({project})")
            valid.append(ks)
        elif status == "leaked":
            print(f"  🚨 {label}  [{project}] → 漏洩・削除して再発行")
            leaked.append((account, project, key_name, ks))
        elif status == "quota":
            print(f"  ⚠️  {label}  [{project}] → クォータ（有効として保持）")
            quota.append(ks)
        else:
            print(f"  ❓ {label}  [{project}] → {status}")

    # 漏洩キーを削除 → 同プロジェクトで再発行
    for account, project, key_name, _ in leaked:
        print(f"\n  🔄 {project} でキーを再発行中...")
        delete_key(key_name, account)
        new_ks = create_key(project, account, display_name="gemini-auto-renewed")
        if new_ks:
            print(f"     → 新キー: {new_ks[:20]}...")
            valid.append(new_ks)
        else:
            print(f"     ❌ 再発行失敗")

    # クォータキーは末尾に追加（ローテーション用）
    all_valid = valid + [k for k in quota if k not in valid]

    # 新規プロジェクト・キー作成
    if create_new:
        accounts = list_accounts()
        for account in accounts:
            projects = list_projects(account)
            if len(projects) < PROJECT_CAP:
                import random, string
                pid = "textseries-" + "".join(random.choices(string.ascii_lowercase, k=8)) + "-api"
                print(f"\n  ➕ 新規プロジェクト {pid} ({account})")
                if create_project(pid, account):
                    enable_gemini_api(pid, account)
                    new_ks = create_key(pid, account)
                    if new_ks:
                        print(f"     → {new_ks[:20]}...")
                        all_valid.append(new_ks)
                    break
            else:
                print(f"  ⚠️  {account} はプロジェクト上限({PROJECT_CAP})")

    save_gemini_keys(all_valid)

    print(f"\n{'='*50}")
    print(f"有効キー: {len(valid)}  クォータ: {len(quota)}  漏洩→再発行: {len(leaked)}")
    return all_valid


def status_only():
    env  = load_env()
    keys = [v for k, v in env.items() if re.match(r"^GEMINI_API_KEY(_\d+)?$", k)]
    print(f"📋 .env内のGeminiキー: {len(keys)}個")
    for i, k in enumerate(keys):
        suffix = "" if i == 0 else f"_{i+1}"
        status = test_key(k)
        icon   = {"ok": "✅", "leaked": "🚨", "quota": "⚠️"}.get(status, "❓")
        print(f"  {icon} GEMINI_API_KEY{suffix}: {k[:20]}...  [{status}]")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--create", action="store_true", help="新規プロジェクト+キー追加")
    parser.add_argument("--status", action="store_true", help="現状表示のみ")
    args = parser.parse_args()

    if args.status:
        status_only()
    else:
        repair_and_update(create_new=args.create)
