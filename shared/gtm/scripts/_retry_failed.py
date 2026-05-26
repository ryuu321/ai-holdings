#!/usr/bin/env python3
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import subprocess, time
from pathlib import Path

FUDOTEXT = Path("C:/Users/ryuuM/fudotext")
GEN = Path("C:/Users/ryuuM/ai-holdings/shared/gtm/scripts/generate_textseries.py")

failed = [
    (33,  "sangyoitext",   "産業医・健康管理室",        "衛生委員会議事録,就業制限意見書,健康管理報告書",  ""),
    (34,  "shurotext",     "障害者就労支援B型",         "個別支援計画,就労記録,利用者評価報告書",          ""),
    (36,  "juitext",       "獣医師・動物病院",          "診療記録,飼い主向け説明書,予防接種管理表",        ""),
    (37,  "gogakutext",    "語学スクール・英会話教室",   "生徒別進捗報告書,保護者向けレポート,カリキュラム提案書",""),
    (38,  "senmontext",    "専門学校",                  "実習日誌添削,就職活動支援書,学習評価報告書",      ""),
    (39,  "keibitext",     "警備会社",                  "警備計画書,事故報告書,業務日報",                  ""),
    (41,  "kyushokutext",  "給食受託会社",              "献立表,栄養管理報告書,衛生管理チェックリスト",    ""),
    (42,  "iryotext",      "医療法人クリニックグループ", "採用説明文,院内規定,研修資料",                   ""),
    (43,  "kaiuntext",     "海運・港湾運送業",          "運送実績報告書,安全管理計画書,積載管理記録",      ""),
    (44,  "kaikeishitext", "会計事務所",                "試算表コメント,決算説明資料,税務調査対応資料",    ""),
    (47,  "chukotext",     "中古車販売業者",            "車両査定報告書,状態説明書,買取提案書",            ""),
    (62,  "yakuzaishitext","薬剤師（病院薬剤部）",      "持参薬鑑別報告書,処方提案書,服薬指導記録",        ""),
    (64,  "reizotext",     "冷凍冷蔵倉庫業者",         "温度管理記録,HACCP関連書類,入出庫管理報告書",     ""),
    (65,  "unsotext",      "運送会社",                  "点呼記録,事故報告書,業務日報",                    ""),
    (66,  "kyuhaisuitext", "給排水設備メンテナンス業者", "設備点検報告書,劣化診断書,修繕提案書",            ""),
    (67,  "nailtext",      "ネイルサロン",              "技術カルテ,SNS集客文,デザイン提案書",             ""),
    (68,  "fptext",        "ファイナンシャルプランナー", "ライフプラン提案書,保険見直し提案書,資産運用計画書",""),
    (70,  "eventtext",     "イベント企画会社",          "企画提案書,運営マニュアル,実施報告書",            ""),
    (86,  "phototext",     "写真スタジオ",              "撮影仕様確認書,修正依頼対応文書,見積書",          ""),
]

ok, ng = 0, []
for rank, slug, industry, docs, emoji in failed:
    if (FUDOTEXT / "saas-dev/projects" / slug).exists():
        print(f"[{rank}] {slug}: skip (exists)")
        ok += 1
        continue
    print(f"\n[{rank}] {slug} retrying...")
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
    time.sleep(5)

print(f"\nretry: {ok}/{len(failed)} OK")
if ng:
    print("failed:", ng)
