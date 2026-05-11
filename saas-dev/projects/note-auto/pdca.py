"""
note PDCA — 週次分析 → アカウント別戦略更新
Usage: python pdca.py
"""
import json
import os
import re
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter

try:
    from google import genai
except ImportError:
    print("pip install google-genai")
    exit(1)

ROOT = Path(__file__).parent

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    env_path = ROOT.parent.parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip()
                break

STRATEGY_FILE = ROOT / "pdca_strategy.json"

GENRES = {
    1: "AI副業・ChatGPT活用系",
    2: "お金・節約・投資入門系",
    3: "就活・転職・キャリア系",
}


def load_state(account_id: int) -> dict:
    f = ROOT / f"state_{account_id}.json"
    if not f.exists():
        return {"posted_topics": [], "articles": []}
    return json.loads(f.read_text(encoding="utf-8"))


def build_stats(account_id: int) -> dict:
    state    = load_state(account_id)
    articles = state.get("articles", [])
    success  = [a for a in articles if a.get("status") == "success"]
    failed   = [a for a in articles if a.get("status") == "failed"]
    prices   = [a["price"] for a in success]
    cutoff   = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    recent   = [a for a in articles if a.get("date", "") >= cutoff]

    return {
        "genre":              GENRES[account_id],
        "total":              len(articles),
        "success":            len(success),
        "failed":             len(failed),
        "success_rate":       round(len(success) / len(articles) * 100, 1) if articles else 0,
        "recent_30d":         len(recent),
        "price_dist":         dict(Counter(prices)),
        "avg_price":          round(sum(prices) / len(prices)) if prices else 0,
        "recent_topics":      state.get("posted_topics", [])[-20:],
    }


def run_pdca():
    now   = datetime.now(timezone.utc)
    stats = {i: build_stats(i) for i in [1, 2, 3]}

    if not API_KEY:
        print("[SKIP] GEMINI_API_KEY未設定")
        return {}

    client = genai.Client(api_key=API_KEY)

    summary = ""
    for acc_id, s in stats.items():
        topics_text = "\n".join(f"  - {t}" for t in s["recent_topics"])
        summary += f"""
=== アカウント{acc_id}: {s['genre']} ===
投稿実績: 計{s['total']}本 / 成功{s['success']}本 / 失敗{s['failed']}本 / 成功率{s['success_rate']}%
直近30日: {s['recent_30d']}本
価格分布: {s['price_dist']}（平均¥{s['avg_price']}）
直近20テーマ（重複不可）:
{topics_text}
"""

    prompt = f"""あなたはnoteの有料記事コンサルタントです。以下の投稿実績を分析し、来週の戦略JSONを出力してください。
今日: {now.strftime('%Y-%m-%d')}

{summary}

条件:
- 直近テーマと被らない新しい切り口を提案
- 価格は内容の厚み・希少性で判断（¥300/500/980）
- タイトルフックは具体的なパターンで（例: 「【月収X万】〜した全手順」）
- noteで今トレンドの話題を意識する

以下のJSONのみ出力（コードブロック・説明文不要）:
{{
  "global_insight": "全体への洞察1-2文（飽和トピック・差別化の余地）",
  "account_strategy": {{
    "1": {{
      "focus": "来週の重点方向性（1文）",
      "next_topics": ["テーマA", "テーマB", "テーマC"],
      "recommended_price": 500,
      "price_reason": "根拠1文",
      "title_hook": "試すべきタイトルパターン（具体例つき）"
    }},
    "2": {{
      "focus": "来週の重点方向性（1文）",
      "next_topics": ["テーマA", "テーマB", "テーマC"],
      "recommended_price": 500,
      "price_reason": "根拠1文",
      "title_hook": "試すべきタイトルパターン（具体例つき）"
    }},
    "3": {{
      "focus": "来週の重点方向性（1文）",
      "next_topics": ["テーマA", "テーマB", "テーマC"],
      "recommended_price": 980,
      "price_reason": "根拠1文",
      "title_hook": "試すべきタイトルパターン（具体例つき）"
    }}
  }}
}}"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(model="gemini-flash-latest", contents=prompt)
            break
        except Exception as e:
            if attempt < 2 and ("429" in str(e) or "503" in str(e) or "RESOURCE_EXHAUSTED" in str(e)):
                print(f"  [WAIT] APIエラー、60秒後リトライ({attempt+1}/2)...")
                time.sleep(60)
            else:
                raise

    text = response.text.strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"JSONが見つかりません: {text[:300]}")

    strategy = json.loads(m.group())
    strategy["updated_at"]    = now.isoformat()
    strategy["account_stats"] = {str(k): v for k, v in stats.items()}

    STRATEGY_FILE.write_text(json.dumps(strategy, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[note PDCA] 戦略更新完了")
    print(f"  洞察: {strategy.get('global_insight', '')}")
    for acc_id in [1, 2, 3]:
        s = strategy.get("account_strategy", {}).get(str(acc_id), {})
        print(f"  Acct{acc_id}: {s.get('focus', '')} / ¥{s.get('recommended_price', '-')}")

    return strategy


if __name__ == "__main__":
    run_pdca()
