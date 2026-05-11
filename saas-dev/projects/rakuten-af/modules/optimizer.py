"""週次プロンプト最適化エンジン"""
import time
from pathlib import Path
from groq import Groq
from config.settings import settings
from core.database import Database


TEMPLATES = ["ranking", "comparison", "story", "howto"]

TEMPLATE_LABELS = {
    "ranking":    "ランキング形式",
    "comparison": "徹底比較形式",
    "story":      "ストーリー形式",
    "howto":      "ハウツー形式",
}


def check_ab_winner(db: Database):
    """14日以上データがあればAB勝者を判定してsettings.pyを更新"""
    ab = db.get_ab_stats(days=14)
    total = ab["A"] + ab["B"]
    if total < 14:
        print(f"[AB] データ不足({total}件)。判定スキップ。")
        return

    print(f"[AB] 14日間: A={ab['A']}件 / B={ab['B']}件")

    if ab["A"] == 0 and ab["B"] == 0:
        return

    # 20%以上の差があれば勝者確定
    if ab["A"] > 0 and ab["B"] > 0:
        ratio = max(ab["A"], ab["B"]) / min(ab["A"], ab["B"])
    else:
        ratio = 999

    if ratio >= 1.2:
        winner = "A" if ab["A"] >= ab["B"] else "B"
        print(f"[AB] 勝者確定: Strategy {winner} (差異{ratio:.1f}倍)")
        _update_ab_winner(winner)
    else:
        print(f"[AB] 差異{ratio:.1f}倍 — まだ判定保留")


def _update_ab_winner(winner: str):
    settings_path = Path(__file__).parent.parent / "config" / "settings.py"
    text = settings_path.read_text(encoding="utf-8")
    import re
    text = re.sub(
        r'AB_WINNER = os\.environ\.get\("AB_WINNER", "[^"]*"\)',
        f'AB_WINNER = os.environ.get("AB_WINNER", "{winner}")',
        text
    )
    settings_path.write_text(text, encoding="utf-8")
    print(f"[AB] settings.py を AB_WINNER={winner} に更新しました")


def run_optimization():
    db = Database()
    client = Groq(api_key=settings.GROQ_API_KEY)

    # AB判定を先に実行
    check_ab_winner(db)

    articles = db.get_recent_articles(limit=30)
    stats = db.get_template_stats()

    print("\n=== 週次最適化分析 ===")
    print(f"分析対象: {len(articles)}記事")
    print("テンプレート使用状況:")
    for s in stats:
        print(f"  {s['template']}: {s['count']}件")

    titles_by_template = {}
    for a in articles:
        t = a.get("template", "ranking")
        if t not in titles_by_template:
            titles_by_template[t] = []
        titles_by_template[t].append(a["title"])

    prompt = f"""
あなたはアフィリエイトブログの最適化専門家です。
以下の楽天アフィリエイト記事の傾向を分析して、購買率を高めるための改善アドバイスをしてください。

## 記事一覧（テンプレート別）
{_format_articles(titles_by_template)}

## テンプレート使用数
{_format_stats(stats)}

## あなたのタスク
各テンプレートに対して、購買につながりやすくするための具体的な改善指示を1〜3文で出してください。
指示はプロンプトに追加される文章として書いてください（「〜してください」形式）。

## 出力形式（JSONのみ、マークダウン不要）
{{
  "ranking": "改善指示文",
  "comparison": "改善指示文",
  "story": "改善指示文",
  "howto": "改善指示文",
  "overall_insight": "全体的な気づき（1〜2文）"
}}
"""

    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            text = resp.choices[0].message.content.strip()
            break
        except Exception as e:
            if attempt < 2:
                print(f"  Groqエラー。リトライ... ({e})")
                time.sleep(15)
            else:
                print(f"  最適化失敗: {e}")
                return

    import re, json
    m = re.search(r"\{[\s\S]+\}", text)
    if not m:
        print(f"  JSON解析失敗:\n{text[:200]}")
        return

    try:
        result = json.loads(m.group())
    except Exception as e:
        print(f"  JSON parse error: {e}")
        return

    overall = result.get("overall_insight", "")
    print(f"\n全体の気づき: {overall}")

    existing = db.conn.execute(
        "SELECT MAX(version) as v FROM prompt_history"
    ).fetchone()
    next_version = (existing["v"] or 0) + 1

    for template in TEMPLATES:
        improvement = result.get(template, "")
        if improvement:
            db.save_prompt_improvement(next_version, template, improvement)
            print(f"  [{TEMPLATE_LABELS[template]}] → {improvement}")

    print(f"\n最適化完了 (v{next_version})")


def _format_articles(titles_by_template: dict) -> str:
    lines = []
    for template, titles in titles_by_template.items():
        lines.append(f"\n【{TEMPLATE_LABELS.get(template, template)}】")
        for t in titles:
            lines.append(f"  - {t}")
    return "\n".join(lines)


def _format_stats(stats: list) -> str:
    return "\n".join(
        f"  {TEMPLATE_LABELS.get(s['template'], s['template'])}: {s['count']}件"
        for s in stats
    )


if __name__ == "__main__":
    run_optimization()
