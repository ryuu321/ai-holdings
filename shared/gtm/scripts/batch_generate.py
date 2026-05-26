#!/usr/bin/env python3
"""
batch_generate.py — ideas_100.md の未生成製品を一括生成

使い方:
  python shared/gtm/scripts/batch_generate.py           # 全未生成製品
  python shared/gtm/scripts/batch_generate.py --start 25 --end 40  # 範囲指定
  python shared/gtm/scripts/batch_generate.py --dry-run  # ファイル非書込
"""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse
import subprocess
import time
from pathlib import Path

AI_HOLDINGS = Path("C:/Users/ryuuM/ai-holdings")
FUDOTEXT    = Path("C:/Users/ryuuM/fudotext")
GEN_SCRIPT  = AI_HOLDINGS / "shared/gtm/scripts/generate_textseries.py"

# ── 全製品定義 (rank: (slug, industry, docs, emoji)) ─────────────────────────
PRODUCTS = {
    18: ("shindantext",    "中小企業診断士事務所",   "経営改善計画書,補助金申請書,事業再生計画書",       "📊"),
    20: ("dobokutext",     "土木・舗装工事業者",     "施工計画書,完成検査報告書,現場安全管理計画書",     "🚧"),
    21: ("sokotext",       "倉庫・物流会社",         "作業手順書,ヒヤリハット報告書,倉庫管理手順書",     "📦"),
    22: ("haikitext",      "産業廃棄物処理業者",     "廃棄物処理計画書,マニフェスト管理報告書,業務実績報告書", "♻️"),
    23: ("bengoshitext",   "弁護士事務所",           "内容証明,依頼者向け説明文書,法律意見書",           "⚖️"),
    25: ("haikantext",     "配管・設備工事業者",     "完工報告書,定期点検記録書,設備改修提案書",         "🔧"),
    26: ("seibitext",      "自動車整備業",           "点検整備記録簿,顧客向け整備説明書,見積書",         "🚗"),
    27: ("sokuryotext",    "測量会社",               "測量報告書,境界確認書,地積測量図説明書",           "📐"),
    28: ("hakentext",      "人材派遣会社",           "派遣契約書,就業条件明示書,スタッフ評価報告書",     "👥"),
    29: ("constext",       "コンサルティング会社",   "提案書,業務改善計画書,プロジェクト完了報告書",     "💼"),
    30: ("ghtext",         "グループホーム（認知症）","個別支援計画,インシデント報告書,モニタリング報告書","🏡"),
    31: ("shokuhintext",   "食品製造業",             "HACCP管理記録,異物混入対応報告書,衛生管理計画書",  "🍱"),
    32: ("naisotext",      "内装工事業者",           "施工計画書,施工完了報告書,内装改修提案書",         "🏗️"),
    33: ("sangyoitext",    "産業医・健康管理室",     "衛生委員会議事録,就業制限意見書,健康管理報告書",   "🩺"),
    34: ("shurotext",      "障害者就労支援B型",      "個別支援計画,就労記録,利用者評価報告書",           "🤝"),
    35: ("kanteitext",     "不動産鑑定士事務所",     "鑑定評価書,市場調査報告書,価格査定報告書",         "🏢"),
    36: ("juitext",        "獣医師・動物病院",       "診療記録,飼い主向け説明書,予防接種管理表",         "🐾"),
    37: ("gogakutext",     "語学スクール・英会話教室","生徒別進捗報告書,保護者向けレポート,カリキュラム提案書","🌍"),
    38: ("senmontext",     "専門学校",               "実習日誌添削,就職活動支援書,学習評価報告書",       "🎓"),
    39: ("keibitext",      "警備会社",               "警備計画書,事故報告書,業務日報",                   "🛡️"),
    40: ("birutext",       "ビルメンテナンス会社",   "設備点検報告書,修繕提案書,定期清掃完了報告書",     "🏬"),
    41: ("kyushokutext",   "給食受託会社",           "献立表,栄養管理報告書,衛生管理チェックリスト",     "🍽️"),
    42: ("iryotext",       "医療法人クリニックグループ","採用説明文,院内規定,研修資料",                  "🏥"),
    43: ("kaiuntext",      "海運・港湾運送業",       "運送実績報告書,安全管理計画書,積載管理記録",       "⚓"),
    44: ("kaikeishitext",  "会計事務所",             "試算表コメント,決算説明資料,税務調査対応資料",     "📒"),
    45: ("fctext",         "フランチャイズ本部",     "加盟店向けマニュアル,指導レポート,FC契約説明書",   "🏪"),
    46: ("kangotext",      "訪問看護ステーション",   "訪問看護指示書受理記録,看護計画書,訪問記録",       "🩺"),
    47: ("chukotext",      "中古車販売業者",         "車両査定報告書,状態説明書,買取提案書",             "🚘"),
    48: ("gasutext",       "ガス・水道工事業者",     "完工届,設備図面説明書,定期点検報告書",             "🔩"),
    49: ("komutentext",    "木造住宅メーカー（工務店）","施主向け工程説明文,引渡し書類,リフォーム提案書", "🏠"),
    50: ("nougyotext",     "農業法人",               "GAP認証書類,農薬使用記録,収穫管理報告書",         "🌾"),
    51: ("insatsutext",    "印刷会社",               "作業指示書,校正確認書,納品仕様書",                 "🖨️"),
    52: ("ryokantext",     "旅館・ホテル",           "宿泊プラン説明文,クレーム対応文書,館内規定",       "🏯"),
    53: ("hokentext",      "保険代理店",             "保険提案書,比較説明書,契約内容確認書",             "📋"),
    54: ("sekizaitext",    "石材・墓石業者",         "施工説明書,完成報告書,見積書",                     "🪨"),
    55: ("kaitaitext",     "解体工事業者",           "解体工事計画書,近隣説明資料,廃材処分報告書",       "🏚️"),
    56: ("extext",         "エクステリア・外構工事業者","外構提案書,完工写真付き報告書,施工計画書",       "🌳"),
    57: ("salontext",      "美容室・ヘアサロン",     "業務マニュアル,SNS集客文,スタイル提案書",          "✂️"),
    58: ("seishintext",    "精神科・心療内科クリニック","診療情報提供書,傷病手当意見書,患者向け説明文",  "🧠"),
    59: ("kensetsuconstext","建設コンサルタント会社","調査報告書,業務完了報告書,技術提案書",             "🔭"),
    60: ("ringyotext",     "林業・製材業者",         "施業計画書,森林経営計画書,木材出荷記録",           "🌲"),
    61: ("pettotext",      "ペットショップ・ペットサロン","健康状態記録,飼育指導書,トリミング報告書",    "🐶"),
    62: ("yakuzaishitext", "薬剤師（病院薬剤部）",  "持参薬鑑別報告書,処方提案書,服薬指導記録",         "💊"),
    63: ("fukushitext",    "社会福祉法人",           "相談支援記録,保護者向け文書,サービス計画書",       "🌸"),
    64: ("reizotext",      "冷凍冷蔵倉庫業者",      "温度管理記録,HACCP関連書類,入出庫管理報告書",      "❄️"),
    65: ("unsotext",       "運送会社",               "点呼記録,事故報告書,業務日報",                     "🚚"),
    66: ("kyuhaisuitext",  "給排水設備メンテナンス業者","設備点検報告書,劣化診断書,修繕提案書",          "🚿"),
    67: ("nailtext",       "ネイルサロン",           "技術カルテ,SNS集客文,デザイン提案書",              "💅"),
    68: ("fptext",         "ファイナンシャルプランナー","ライフプラン提案書,保険見直し提案書,資産運用計画書","💰"),
    69: ("iryokikitext",   "医療機器販売業者",       "機器説明資料,定期点検報告書,導入提案書",           "🔬"),
    70: ("eventtext",      "イベント企画会社",       "企画提案書,運営マニュアル,実施報告書",             "🎪"),
    71: ("fittext",        "スポーツジム・フィットネス","プログラム説明書,体験案内文,トレーニング計画書",  "💪"),
    72: ("sogitext",       "葬儀社",                 "葬儀プラン説明書,アフターフォロー案内,見積書",     "🕊️"),
    73: ("kogutext",       "機械工具卸売業者",       "商品仕様説明書,導入事例資料,見積書",               "⚙️"),
    74: ("yakuhintext",    "薬品・化学品製造業者",   "安全データシート,品質管理記録,製品仕様書",         "🧪"),
    75: ("yanetext",       "建築板金・屋根工事業者", "屋根診断報告書,施工完了報告書,修繕提案書",         "🏠"),
    76: ("seisoutext",     "清掃会社（法人向け）",   "作業計画書,作業報告書,清掃仕様確認書",             "🧹"),
    77: ("deliverytext",   "宅配・デリバリー加盟店", "衛生管理記録,配送ルート報告書,業務マニュアル",     "🛵"),
    78: ("gyogyotext",     "漁業（養殖・定置網）",   "漁獲記録,品質管理報告書,出荷管理表",               "🐟"),
    79: ("sekkotsutext",   "ウェルネス・整体院",     "施術記録,患者向け説明書,症状経過報告書",           "💆"),
    80: ("sonpohokentext", "損害保険代理店",         "事故対応報告書,示談交渉補助文書,保険提案書",       "🛡️"),
    81: ("shogyotext",     "司法書士補助（商業登記）","株主総会議事録,取締役会議事録,登記申請書",        "📑"),
    82: ("zoentext",       "造園・緑化工事業者",     "施工計画書,工事完了報告書,緑化提案書",             "🌿"),
    83: ("iyakuhintext",   "医薬品卸売業者",         "販促資料,取引先向け報告書,製品説明書",             "💉"),
    84: ("shushokutext",   "就職支援会社",           "キャリアプラン提案書,就職活動報告書,面談記録",     "👔"),
    85: ("drugtext",       "ドラッグストア",         "薬剤服用歴管理記録,業務マニュアル,接客マニュアル", "🏥"),
    86: ("phototext",      "写真スタジオ",           "撮影仕様確認書,修正依頼対応文書,見積書",           "📸"),
    87: ("gakudotext",     "学童保育（民間）",       "保護者向け月次報告書,安全対策説明書,活動記録",     "🎒"),
    88: ("mokkotext",      "木工・家具製造業者",     "製品仕様書,品質検査記録,製作指示書",               "🪵"),
    89: ("hashitext",      "建設業（橋梁・鋼構造物）","品質管理計画書,完成検査記録書,施工報告書",        "🌉"),
    90: ("tenjikaitext",   "展示会・見本市運営会社", "出展者向け説明資料,運営マニュアル,実施報告書",     "🎡"),
    91: ("yurohokentext",  "有料老人ホーム（民間）", "入居契約説明書,家族向け報告書,ケアプラン",         "🏡"),
    92: ("nokitext",       "農業機械修理業者",       "修理作業報告書,点検整備記録,見積書",               "🚜"),
    93: ("supertext",      "地場スーパー・食品小売", "仕入先交渉用資料,食品表示確認書,衛生管理記録",     "🛒"),
    94: ("yunyutext",      "輸入食品卸業者",         "成分表示確認書,商品説明書,輸入検査記録",           "🚢"),
    95: ("braidaltext",    "ブライダル会社",         "挙式プラン提案書,演出進行表,当日タイムライン",     "💍"),
    96: ("shinkyutext",    "鍼灸院",                 "施術記録,養生指導書,症状改善報告書",               "🪡"),
    97: ("ihintext",       "遺品整理業者",           "作業完了報告書,廃棄物処分証明書,お見積書",         "📦"),
    98: ("suisantext",     "水産加工業者",           "HACCP管理記録,アレルゲン管理書類,品質検査記録",   "🐠"),
    99: ("kyoshujotext",   "自動車教習所",           "教習進捗管理表,保護者向け説明文書,技能評価記録",   "🚦"),
   100: ("flowertext",    "フラワーショップ（法人装花）","装花仕様確認書,施工報告書,見積書",             "💐"),
}

# 既にfudotextリポジトリに存在する製品をスキップ
EXISTING = {p.name for p in (FUDOTEXT / "saas-dev/projects").iterdir() if p.is_dir()}


def already_done(slug: str) -> bool:
    return slug in EXISTING


def run_product(rank: int, slug: str, industry: str, docs: str, emoji: str,
                dry_run: bool) -> bool:
    if already_done(slug):
        print(f"  [{rank:3d}] {slug}: ✅ 既存スキップ")
        return True

    print(f"\n{'='*60}")
    print(f"  [{rank:3d}] {slug} ({industry})")
    print(f"  書類: {docs}")

    cmd = [
        sys.executable, str(GEN_SCRIPT),
        "--slug", slug,
        "--industry", industry,
        "--docs", docs,
        "--emoji", emoji,
        "--rank", str(rank),
    ]
    if dry_run:
        cmd.append("--dry-run")

    t0 = time.time()
    r = subprocess.run(cmd, capture_output=False, text=True, encoding="utf-8", errors="replace")
    elapsed = time.time() - t0
    if r.returncode == 0:
        print(f"  ✅ 完了 ({elapsed:.0f}s)")
        return True
    else:
        print(f"  ❌ 失敗 (exit={r.returncode}, {elapsed:.0f}s)")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start",   type=int, default=1,   help="開始ランク")
    parser.add_argument("--end",     type=int, default=100, help="終了ランク")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    targets = [(rank, *info) for rank, info in sorted(PRODUCTS.items())
               if args.start <= rank <= args.end]

    print(f"対象: {len(targets)} 製品 (rank {args.start}〜{args.end})")
    already = sum(1 for _, slug, *_ in targets if already_done(slug))
    print(f"既存スキップ予定: {already} / 実際に生成: {len(targets)-already}")

    ok, ng = 0, []
    for rank, slug, industry, docs, emoji in targets:
        success = run_product(rank, slug, industry, docs, emoji, args.dry_run)
        if success:
            ok += 1
        else:
            ng.append(f"[{rank}] {slug}")
        # API過負荷対策: 製品間で短い待機
        if not already_done(slug):
            time.sleep(3)

    print(f"\n{'='*60}")
    print(f"完了: {ok}/{len(targets)}")
    if ng:
        print(f"失敗: {', '.join(ng)}")


if __name__ == "__main__":
    main()
