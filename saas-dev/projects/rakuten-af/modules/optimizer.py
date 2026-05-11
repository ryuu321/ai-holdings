"""週次PDCA最適化エンジン — 実CVR/クリックデータ + マーケティング改善"""
import re
import json
import time
from pathlib import Path
from groq import Groq
from config.settings import settings
from core.database import Database
from modules.af_scraper import load_stats

TEMPLATES = ["ranking", "comparison", "story", "howto"]

TEMPLATE_LABELS = {
    "ranking":    "ランキング形式",
    "comparison": "徹底比較形式",
    "story":      "ストーリー形式",
    "howto":      "ハウツー形式",
}


def check_ab_winner(db: Database):
    ab = db.get_ab_stats(days=14)
    total = ab["A"] + ab["B"]
    if total < 14:
        print(f"[AB] データ不足({total}件)。判定スキップ。")
        return

    print(f"[AB] 14日間: A={ab['A']}件 / B={ab['B']}件")
    if ab["A"] == 0 or ab["B"] == 0:
        return

    ratio = max(ab["A"], ab["B"]) / min(ab["A"], ab["B"])
    if ratio >= 1.2:
        winner = "A" if ab["A"] >= ab["B"] else "B"
        print(f"[AB] 勝者確定: Strategy {winner} (差異{ratio:.1f}倍)")
        _update_ab_winner(winner)
    else:
        print(f"[AB] 差異{ratio:.1f}倍 — 判定保留")


def _update_ab_winner(winner: str):
    settings_path = Path(__file__).parent.parent / "config" / "settings.py"
    text = settings_path.read_text(encoding="utf-8")
    text = re.sub(
        r'AB_WINNER = os\.environ\.get\("AB_WINNER", "[^"]*"\)',
        f'AB_WINNER = os.environ.get("AB_WINNER", "{winner}")',
        text
    )
    settings_path.write_text(text, encoding="utf-8")
    print(f"[AB] settings.py を AB_WINNER={winner} に更新しました")


def _summarize_stats(stats: list[dict]) -> dict:
    """AF実績データを集計してサマリを返す。"""
    if not stats:
        return {"total_clicks": 0, "total_purchases": 0, "avg_cvr": 0.0, "total_commission": 0, "trend": "データなし"}

    total_clicks    = sum(s["clicks"] for s in stats)
    total_purchases = sum(s["purchases"] for s in stats)
    total_commission = sum(s["commission"] for s in stats)
    avg_cvr = round(total_purchases / total_clicks * 100, 2) if total_clicks > 0 else 0.0

    # 前半・後半でCVRを比較してトレンドを判定
    mid = len(stats) // 2
    first_half  = stats[:mid]
    second_half = stats[mid:]
    cvr_first  = sum(s["purchases"] for s in first_half)  / max(sum(s["clicks"] for s in first_half), 1)  * 100
    cvr_second = sum(s["purchases"] for s in second_half) / max(sum(s["clicks"] for s in second_half), 1) * 100

    if cvr_second > cvr_first * 1.1:
        trend = "改善中（CVR上昇傾向）"
    elif cvr_second < cvr_first * 0.9:
        trend = "悪化中（CVR低下傾向）"
    else:
        trend = "横ばい"

    # 高CVR日・低CVR日を特定
    sorted_by_cvr = sorted([s for s in stats if s["clicks"] >= 5], key=lambda x: x["cvr"], reverse=True)
    best_days  = sorted_by_cvr[:3]
    worst_days = sorted_by_cvr[-3:] if len(sorted_by_cvr) >= 3 else []

    return {
        "total_clicks":    total_clicks,
        "total_purchases": total_purchases,
        "avg_cvr":         avg_cvr,
        "total_commission": total_commission,
        "trend":           trend,
        "best_days":       best_days,
        "worst_days":      worst_days,
    }


def _load_room_category_stats() -> dict:
    """products.csv からカテゴリ別投稿済み件数・平均スコアを集計（pandas不使用）。"""
    import csv
    csv_path = Path(__file__).parent.parent.parent / "rakuten-room" / "data" / "products.csv"
    if not csv_path.exists():
        return {}
    cats: dict[str, dict] = {}
    try:
        with open(csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cat = row.get("category", "不明") or "不明"
                if cat not in cats:
                    cats[cat] = {"posted": 0, "pending": 0, "total_score": 0.0, "count": 0}
                posted = row.get("posted", "") == "True"
                score  = float(row.get("score", 0) or 0)
                if posted:
                    cats[cat]["posted"] += 1
                else:
                    cats[cat]["pending"] += 1
                cats[cat]["total_score"] += score
                cats[cat]["count"] += 1
    except Exception:
        pass
    for v in cats.values():
        v["avg_score"] = round(v["total_score"] / v["count"], 2) if v["count"] else 0
    return cats


def run_room_pdca(client: Groq, summary: dict):
    """楽天ROOM投稿のキャプション・カテゴリ戦略を週次で最適化する。"""
    cat_stats = _load_room_category_stats()

    # カテゴリ別に「保留数 × 平均スコア」でソート → 優先カテゴリ上位5
    top_cats = sorted(
        cat_stats.items(),
        key=lambda kv: kv[1]["pending"] * kv[1]["avg_score"],
        reverse=True,
    )[:8]
    cat_text = "\n".join(
        f"  {c}: 未投稿{v['pending']}件 / 投稿済み{v['posted']}件 / 平均スコア{v['avg_score']}"
        for c, v in top_cats
    )

    prompt = f"""あなたは楽天ROOMアフィリエイトのマーケティング専門家です。
楽天ROOMの投稿キャプション（SNS風の紹介文）を最適化し、クリック率とCVRを上げてください。
楽天ROOMは画像+短文キャプションでユーザーが商品を紹介するSNSです。購入はキャプション内のリンクから発生します。

## 過去30日の実績（楽天AF = ROOM経由100%）
- クリック合計: {summary['total_clicks']}
- 購入合計:     {summary['total_purchases']}
- 平均CVR:      {summary['avg_cvr']}%
- 報酬合計:     ¥{summary['total_commission']}
- トレンド:     {summary['trend']}

## 投稿カテゴリ在庫（未投稿 × スコア順）
{cat_text or '  データなし'}

## 出力（JSONのみ）
{{
  "priority_category": "最優先で投稿すべきカテゴリ名（1つ）",
  "hook_short": "短文フック例（40字以内）。共感・驚き・数字のどれかを必ず入れる",
  "hook_mom": "ママ向けフック例（40字以内）。育児・家事・節約で共感を引く",
  "cta_text": "商品リンク誘導のCTA（20字以内）。例：↓詳細はこちら",
  "avoid_pattern": "NGワード・避けるべき表現（50字以内）",
  "overall_insight": "最優先改善ポイント（80字以内）",
  "weekly_target_posts": 投稿目標件数（整数）
}}"""

    result = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
                max_tokens=600,
            )
            text = resp.choices[0].message.content.strip()
            m = re.search(r"\{[\s\S]+\}", text)
            if m:
                result = json.loads(m.group(), strict=False)
            break
        except Exception as e:
            if attempt < 2:
                print(f"  [ROOM PDCA] Groqエラー。リトライ... ({e})")
                time.sleep(15)
            else:
                print(f"  [ROOM PDCA] 失敗: {e}")
                return

    if not result:
        print("  [ROOM PDCA] JSON解析失敗。スキップ。")
        return

    log_path = Path(__file__).parent.parent / "data" / "room_pdca_log.json"
    from datetime import datetime, timezone
    entry = {
        "updated_at":        datetime.now(timezone.utc).isoformat(),
        "priority_category": result.get("priority_category", ""),
        "hook_short":        result.get("hook_short", ""),
        "hook_mom":          result.get("hook_mom", ""),
        "cta_text":          result.get("cta_text", ""),
        "avoid_pattern":     result.get("avoid_pattern", ""),
        "overall_insight":   result.get("overall_insight", ""),
        "weekly_target_posts": result.get("weekly_target_posts", 0),
        "af_summary":        summary,
    }
    log_path.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n[ROOM PDCA]")
    print(f"  優先カテゴリ:  {result.get('priority_category', '')}")
    print(f"  フック例:      {result.get('hook_short', '')}")
    print(f"  CTA:           {result.get('cta_text', '')}")
    print(f"  気づき:        {result.get('overall_insight', '')}")
    print(f"  週間目標:      {result.get('weekly_target_posts', 0)}件")


def run_optimization():
    db = Database()
    client = Groq(api_key=settings.GROQ_API_KEY)

    check_ab_winner(db)

    # 実パフォーマンスデータ取得
    stats = load_stats(days=30)
    summary = _summarize_stats(stats)

    articles = db.get_recent_articles(limit=30)

    print("\n=== 週次PDCA最適化 ===")
    print(f"  クリック合計: {summary['total_clicks']}")
    print(f"  購入合計:     {summary['total_purchases']}")
    print(f"  平均CVR:      {summary['avg_cvr']}%")
    print(f"  報酬合計:     ¥{summary['total_commission']}")
    print(f"  トレンド:     {summary['trend']}")

    # ① ROOM PDCA（主軸）
    run_room_pdca(client, summary)

    # ② Hatena ブログテンプレート改善（サブ）
    titles_by_template: dict[str, list[str]] = {}
    for a in articles:
        t = a.get("template", "ranking")
        titles_by_template.setdefault(t, []).append(a["title"])

    best_days_text  = "\n".join(f"  {d['date']}: CVR{d['cvr']}% クリック{d['clicks']}" for d in summary["best_days"])
    worst_days_text = "\n".join(f"  {d['date']}: CVR{d['cvr']}% クリック{d['clicks']}" for d in summary["worst_days"])

    prompt = f"""あなたは楽天アフィリエイトのコンバージョン最適化の専門家です。
以下の実績データと記事タイトルを分析し、購買率（CVR）を上げるための具体的な改善指示を出してください。

## 過去30日の実績
- クリック合計: {summary['total_clicks']}
- 購入合計: {summary['total_purchases']}
- 平均CVR: {summary['avg_cvr']}%
- トレンド: {summary['trend']}

## CVR高い日（参考）
{best_days_text or '  データなし'}

## CVR低い日（参考）
{worst_days_text or '  データなし'}

## 記事タイトル（テンプレート別）
{_format_articles(titles_by_template)}

## 改善指示の要件
各テンプレートについて、以下の観点を含む具体的な改善指示を出してください:
1. **フック（冒頭3行）**: 読者を離脱させないための書き出し
2. **見出し（H2）**: クリックしたくなる見出しの型
3. **CTA（行動喚起）**: 商品リンク前後の購買を促すテキスト
4. **訴求軸**: 価格・レビュー・限定性・緊急性のどれを前面に出すか

指示はそのまま記事生成プロンプトに追記される文章として書いてください。

## 出力（JSONのみ）
{{
  "ranking":    "改善指示（200字以内）",
  "comparison": "改善指示（200字以内）",
  "story":      "改善指示（200字以内）",
  "howto":      "改善指示（200字以内）",
  "overall_insight": "全体の気づきと最優先改善点（100字以内）",
  "niche_recommendation": "次週注力すべきニッチカテゴリ（例: コスメ・食品など）"
}}"""

    result = None
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
                max_tokens=800,
            )
            text = resp.choices[0].message.content.strip()
            m = re.search(r"\{[\s\S]+\}", text)
            if m:
                result = json.loads(m.group(), strict=False)
            break
        except Exception as e:
            if attempt < 2:
                print(f"  Groqエラー。リトライ... ({e})")
                time.sleep(15)
            else:
                print(f"  最適化失敗: {e}")
                return

    if not result:
        print("  JSON解析失敗。スキップ。")
        return

    print(f"\n気づき: {result.get('overall_insight', '')}")
    print(f"次週注力ニッチ: {result.get('niche_recommendation', '')}")

    existing = db.conn.execute("SELECT MAX(version) as v FROM prompt_history").fetchone()
    next_version = (existing["v"] or 0) + 1

    for template in TEMPLATES:
        improvement = result.get(template, "")
        if improvement:
            db.save_prompt_improvement(next_version, template, improvement)
            print(f"  [{TEMPLATE_LABELS[template]}] → {improvement[:80]}...")

    # サマリをJSONで保存（ダッシュボード用）
    _save_pdca_log(summary, result)
    print(f"\n最適化完了 (v{next_version})")


def _save_pdca_log(summary: dict, result: dict):
    """最新PDCA結果をJSONに保存（ダッシュボード表示用）"""
    log_file = Path(__file__).parent.parent / "data" / "pdca_log.json"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    entry = {
        "updated_at":          datetime.now(timezone.utc).isoformat(),
        "avg_cvr":             summary["avg_cvr"],
        "trend":               summary["trend"],
        "overall_insight":     result.get("overall_insight", ""),
        "niche_recommendation": result.get("niche_recommendation", ""),
    }
    log_file.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")


def _format_articles(titles_by_template: dict) -> str:
    lines = []
    for template, titles in titles_by_template.items():
        lines.append(f"\n【{TEMPLATE_LABELS.get(template, template)}】")
        for t in titles[:10]:
            lines.append(f"  - {t}")
    return "\n".join(lines)


if __name__ == "__main__":
    run_optimization()
