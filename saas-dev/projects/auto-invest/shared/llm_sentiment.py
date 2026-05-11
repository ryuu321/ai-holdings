"""
金融特化感情分析モジュール

優先順位:
  1. FinBERT (ProsusAI/finbert) — 無料・ローカル・金融専用BERT
     初回のみモデルDL (~440MB)、以降はキャッシュ使用
  2. Claude API (ANTHROPIC_API_KEY が設定されている場合)
  3. キーワードマッチング (フォールバック)

【FinBERTとは】
  金融テキスト4,500件でfine-tuningされたBERTモデル
  「株価は下落したが利益予想を上回った」のような複雑な文脈を理解
  キーワードマッチングより大幅に精度向上

【研究実績】
  金融感情分析精度: ~85% (vs キーワード: ~55%)
"""
from __future__ import annotations
import json
import os
from typing import Optional

# キーワードフォールバック用
POSITIVE_WORDS = [
    "bullish","surge","rally","adoption","breakout","record","growth",
    "gains","recovery","upgrade","partnership","launch","approval","etf",
    "institutional","rate cut","stimulus","dovish","expansion"
]
NEGATIVE_WORDS = [
    "bearish","crash","ban","hack","regulation","lawsuit","sell","drop",
    "fall","decline","risk","warning","fraud","scam","exploit","liquidation",
    "recession","inflation","rate hike","hawkish","crisis","war","sanctions"
]

# モデルキャッシュ（プロセス内で1回だけロード）
_finbert_pipeline = None
_finbert_failed   = False


def _load_finbert():
    """FinBERTパイプラインをロード（初回のみDL）"""
    global _finbert_pipeline, _finbert_failed
    if _finbert_pipeline is not None:
        return _finbert_pipeline
    if _finbert_failed:
        return None
    try:
        from transformers import pipeline
        print("    [FinBERT] モデルロード中 (初回はDLに数分かかります)...")
        _finbert_pipeline = pipeline(
            "text-classification",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
            top_k=None,          # 全クラスのスコアを返す
            truncation=True,
            max_length=512,
        )
        print("    [FinBERT] ロード完了")
        return _finbert_pipeline
    except Exception as e:
        print(f"    [FinBERT] ロード失敗: {e}")
        _finbert_failed = True
        return None


def _finbert_sentiment(articles: list[dict]) -> dict:
    """
    FinBERTによる感情分析
    各記事のタイトル+サマリーを個別に分析して集計
    """
    pipe = _load_finbert()
    if pipe is None:
        return None  # フォールバックへ

    texts = []
    for a in articles[:12]:
        title   = a.get("title", "")
        summary = a.get("summary", "")
        text    = (title + " " + summary).strip()[:512]
        if text:
            texts.append(text)

    if not texts:
        return None

    try:
        results = pipe(texts)

        # 各記事のスコアを集計
        pos_total = neg_total = neu_total = 0.0
        for res in results:
            # res は [{"label": "positive", "score": 0.9}, ...] のリスト
            scores = {r["label"]: r["score"] for r in res}
            pos_total += scores.get("positive", 0)
            neg_total += scores.get("negative", 0)
            neu_total += scores.get("neutral",  0)

        n = len(results)
        pos_avg = pos_total / n
        neg_avg = neg_total / n
        neu_avg = neu_total / n

        # -5〜+5 のスコアに変換
        raw_score = (pos_avg - neg_avg) * 5.0

        # 支配的な感情ラベルを決定
        if pos_avg > neg_avg and pos_avg > neu_avg:
            label = "bullish"
        elif neg_avg > pos_avg and neg_avg > neu_avg:
            label = "bearish"
        else:
            label = "neutral"

        # 信頼度: 最大クラスの確信度
        confidence = max(pos_avg, neg_avg, neu_avg)

        return {
            "score":       round(raw_score, 3),
            "label":       label,
            "key_factors": [],
            "confidence":  round(confidence, 3),
            "method":      "finbert",
            "detail": {
                "positive": round(pos_avg, 3),
                "negative": round(neg_avg, 3),
                "neutral":  round(neu_avg, 3),
            },
        }
    except Exception as e:
        print(f"    [FinBERT] 推論エラー: {e}")
        return None


def _claude_sentiment(articles: list[dict], context: str) -> Optional[dict]:
    """Claude API感情分析（APIキーがある場合のオプション）"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    headlines = "\n".join(
        f"- {a.get('title','')}" for a in articles[:12] if a.get("title")
    )
    if not headlines.strip():
        return None

    prompt = f"""以下の{context}関連ニュース見出しを分析してください。

{headlines}

以下のJSONのみを返してください（説明不要）:
{{
  "score": <-5.0〜5.0の数値。強い弱気=-5、中立=0、強い強気=+5>,
  "label": "<bullish|bearish|neutral>",
  "key_factors": ["<重要なポイント1>", "<重要なポイント2>"],
  "confidence": <0.0〜1.0>
}}"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"): raw = raw[4:]
        data = json.loads(raw)
        return {
            "score":        float(data.get("score", 0)),
            "label":        data.get("label", "neutral"),
            "key_factors":  data.get("key_factors", []),
            "confidence":   float(data.get("confidence", 0.7)),
            "method":       "claude",
        }
    except Exception:
        return None


def _keyword_sentiment(articles: list[dict]) -> dict:
    """フォールバック: キーワードマッチング"""
    score = 0
    for a in articles:
        text = (a.get("title","") + " " + a.get("summary","")).lower()
        for w in POSITIVE_WORDS: score += text.count(w)
        for w in NEGATIVE_WORDS: score -= text.count(w)
    normalized = max(-5.0, min(5.0, score / max(len(articles), 1)))
    return {
        "score":       normalized,
        "raw_score":   score,
        "label":       "bullish" if score > 0 else ("bearish" if score < 0 else "neutral"),
        "key_factors": [],
        "method":      "keyword",
        "confidence":  0.4,
    }


def analyze_with_claude(articles: list[dict], context: str = "crypto") -> dict:
    """
    感情分析のメインエントリーポイント。
    優先順位: FinBERT > Claude API > キーワード
    """
    if not articles:
        return {"score": 0.0, "label": "neutral", "key_factors": [],
                "method": "none", "confidence": 0.5}

    # 1. FinBERT（無料・ローカル・推奨）
    result = _finbert_sentiment(articles)
    if result is not None:
        return result

    # 2. Claude API（APIキーがある場合）
    result = _claude_sentiment(articles, context)
    if result is not None:
        return result

    # 3. キーワードフォールバック
    return _keyword_sentiment(articles)


def sentiment_to_signal(sentiment: dict) -> tuple[int, str]:
    """
    感情スコア → シグナルスコア (-2〜+2)
    FinBERTは信頼度が高いのでスコアをそのまま使用
    """
    score  = sentiment.get("score", 0)
    label  = sentiment.get("label", "neutral")
    method = sentiment.get("method", "keyword")
    conf   = sentiment.get("confidence", 0.5)
    factors = sentiment.get("key_factors", [])
    factor_str = " / ".join(factors[:2]) if factors else ""

    # FinBERTは信頼度が高いのでconfによる減衰を小さくする
    decay = 0.8 if method == "finbert" else conf
    effective = score * decay

    if effective >= 3.0:
        sig = +2
        reason = f"感情分析: 強い強気({score:+.1f}) [{method}] {factor_str}"
    elif effective >= 1.5:
        sig = +1
        reason = f"感情分析: やや強気({score:+.1f}) [{method}] {factor_str}"
    elif effective <= -3.0:
        sig = -2
        reason = f"感情分析: 強い弱気({score:+.1f}) [{method}] {factor_str}"
    elif effective <= -1.5:
        sig = -1
        reason = f"感情分析: やや弱気({score:+.1f}) [{method}] {factor_str}"
    else:
        sig = 0
        reason = f"感情分析: 中立({score:+.1f}) [{method}]"

    return sig, reason
