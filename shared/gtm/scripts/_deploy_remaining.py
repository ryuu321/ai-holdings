#!/usr/bin/env python3
import sys, subprocess, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from deploy_cloudrun import deploy_product, load_pools, load_registry

REMAINING = "aftertext,cmtext,daytext,denkitext,gyotext,mokkotext,nailtext,naisotext,nokitext,nougyotext,pettotext,phototext,reizotext,ringyotext,ryokantext,salontext,sangyoitext,seibitext,seishintext,seisoutext,sekizaitext,senmontext,shindantext,shinkyutext,shogyotext,shokuhintext,shurotext,shushokutext,sogitext,sokotext,sokuryotext,sonpohokentext,suisantext,supertext,tenjikaitext,tokutext,tokuyoutext,unsotext,yakuhintext,yakuzaishitext,yanetext,yunyutext,yurohokentext,zoentext".split(",")

pool_map = load_pools()
registry = load_registry()

ok, ng = 0, []
for slug in REMAINING:
    try:
        if deploy_product(slug, pool_map, registry):
            ok += 1
        else:
            ng.append(slug)
    except Exception as e:
        print(f"  ERROR {slug}: {e}")
        ng.append(slug)

print(f"\n{'='*50}")
print(f"完了: {ok}/{len(REMAINING)}")
if ng:
    print(f"失敗: {','.join(ng)}")
