#!/usr/bin/env python3
"""
batch_setup_stripe.py — 全製品に Stripe/GCP/Supabase を一括セットアップ

generate_textseries.py の後に実行する。
config JSON が存在する全製品を対象に setup_stripe.py を呼ぶ。

使い方:
  python shared/gtm/scripts/batch_setup_stripe.py           # 全製品
  python shared/gtm/scripts/batch_setup_stripe.py --slug shindantext  # 単品
  python shared/gtm/scripts/batch_setup_stripe.py --missing-only      # Stripe未設定のみ
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse
import json
import subprocess
import time
from pathlib import Path

AI_HOLDINGS  = Path("C:/Users/ryuuM/ai-holdings")
CFG_DIR      = AI_HOLDINGS / "shared/gtm/config"
SETUP_SCRIPT = AI_HOLDINGS / "shared/gtm/scripts/setup_stripe.py"

# 既に stripe_standard_url があるものはスキップ可能
def has_stripe(cfg_path: Path) -> bool:
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return bool(cfg.get("stripe_standard_url", ""))
    except Exception:
        return False


def run_setup(slug: str) -> bool:
    cfg_path = CFG_DIR / f"{slug}.json"
    if not cfg_path.exists():
        print(f"  ⚠️  {slug}: config JSON なし → スキップ")
        return False

    print(f"\n{'─'*50}")
    print(f"  🔧 {slug}")
    t0 = time.time()
    r = subprocess.run(
        [sys.executable, str(SETUP_SCRIPT), "--project", slug],
        capture_output=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.time() - t0
    if r.returncode == 0:
        print(f"  ✅ 完了 ({elapsed:.0f}s)")
        return True
    else:
        print(f"  ❌ 失敗 (exit={r.returncode}, {elapsed:.0f}s)")
        return False


def get_all_slugs() -> list[str]:
    slugs = []
    for p in sorted(CFG_DIR.glob("*.json")):
        if p.stem == "gcp_pools":
            continue
        slugs.append(p.stem)
    return slugs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slug",         help="単品スラッグ")
    parser.add_argument("--missing-only", action="store_true",
                        help="stripe_standard_url が未設定の製品のみ")
    parser.add_argument("--yes", "-y",    action="store_true", help="確認プロンプトをスキップ")
    args = parser.parse_args()

    if args.slug:
        slugs = [args.slug]
    else:
        slugs = get_all_slugs()

    if args.missing_only:
        slugs = [s for s in slugs if not has_stripe(CFG_DIR / f"{s}.json")]

    print(f"対象: {len(slugs)} 製品")
    for s in slugs:
        has = has_stripe(CFG_DIR / f"{s}.json")
        print(f"  {'✅' if has else '──'} {s}")

    if not args.yes:
        confirm = input("\n実行しますか？ [y/N]: ").strip().lower()
        if confirm != "y":
            print("キャンセル")
            return

    ok, ng = 0, []
    for slug in slugs:
        if run_setup(slug):
            ok += 1
        else:
            ng.append(slug)

    print(f"\n{'='*50}")
    print(f"完了: {ok}/{len(slugs)}")
    if ng:
        print(f"失敗: {', '.join(ng)}")


if __name__ == "__main__":
    main()
