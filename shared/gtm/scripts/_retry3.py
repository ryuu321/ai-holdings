#!/usr/bin/env python3
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import subprocess, time
from pathlib import Path

FUDOTEXT = Path("C:/Users/ryuuM/fudotext")
GEN = Path("C:/Users/ryuuM/ai-holdings/shared/gtm/scripts/generate_textseries.py")

todo = [
    (43, "kaiuntext",     "海運・港湾運送業",   "運送実績報告書,安全管理計画書,積載管理記録",    ""),
    (44, "kaikeishitext", "会計事務所",          "試算表コメント,決算説明資料,税務調査対応資料",  ""),
    (47, "chukotext",     "中古車販売業者",      "車両査定報告書,状態説明書,買取提案書",          ""),
]

ok, ng = 0, []
for rank, slug, industry, docs, emoji in todo:
    if (FUDOTEXT / "saas-dev/projects" / slug).exists():
        print(f"[{rank}] {slug}: skip")
        ok += 1
        continue
    print(f"\n[{rank}] {slug}...")
    r = subprocess.run(
        [sys.executable, str(GEN), "--slug", slug, "--industry", industry,
         "--docs", docs, "--emoji", emoji or "📄", "--rank", str(rank), "--no-stripe"],
        text=True, encoding="utf-8", errors="replace"
    )
    if r.returncode == 0:
        print(f"[{rank}] {slug}: OK")
        ok += 1
    else:
        print(f"[{rank}] {slug}: FAILED")
        ng.append(slug)
    time.sleep(8)

print(f"\n{ok}/{len(todo)} OK")
if ng:
    print("failed:", ng)
