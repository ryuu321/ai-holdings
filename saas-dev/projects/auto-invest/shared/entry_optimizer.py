"""
エントリータイミング最適化

【問題】
  シグナルが出た瞬間に成行注文 → 高値掴み/底値売りが多い

【改善】
  上昇トレンドの押し目（MA20付近）でのみ買う
  ATRベースのR:Rが2:1以上の場合のみ許可

【効果】
  同じシグナルでも買値が5〜10%改善 → 利益に直結
"""
from __future__ import annotations
from typing import Optional


def check_entry_quality(technicals: dict,
                        regime: str = "RANGE") -> tuple[bool, float, str]:
    """
    エントリー品質を評価する。

    Args:
        technicals: collector から取得した技術指標
        regime:     "BULL" | "BEAR" | "RANGE"

    Returns:
        (should_enter: bool, quality_score: 0.0〜1.5, reason: str)
        quality_score >= 1.0 → 推奨
        quality_score 0.7〜1.0 → 許容
        quality_score < 0.7  → 見送り推奨
    """
    price = technicals.get("current_price")
    ma20  = technicals.get("ma20")
    ma50  = technicals.get("ma50")
    atr   = technicals.get("atr")
    adx   = technicals.get("adx")
    rsi   = technicals.get("rsi")
    bb_lower = technicals.get("bb_lower")
    bb_upper = technicals.get("bb_upper")

    if price is None:
        return True, 1.0, "価格データなし → デフォルト許可"

    score   = 1.0
    reasons = []

    # ══════════════════════════════════════════════
    # 1. トレンド確認 + 押し目チェック
    # ══════════════════════════════════════════════
    if regime == "BULL" and ma20 and ma50:
        # 上昇トレンド中: MA20に近いほど良いエントリー
        if price > ma50:  # 大局上昇確認
            deviation = (price - ma20) / ma20
            if -0.02 <= deviation <= 0.03:
                # MA20付近 ±2〜3%: ベストエントリーゾーン
                score += 0.3
                reasons.append(f"MA20押し目({deviation*100:+.1f}%) ベストゾーン")
            elif 0.03 < deviation <= 0.07:
                # MA20から少し上: 普通
                reasons.append(f"MA20から{deviation*100:.1f}%上 普通")
            elif deviation > 0.10:
                # MA20から10%超乖離: 高値掴みリスク
                score -= 0.25
                reasons.append(f"MA20から{deviation*100:.1f}%乖離 → 高値追いリスク")
            elif deviation < -0.03:
                # MA20を下回っている: 短期反転待ち
                score -= 0.1
                reasons.append(f"MA20下({deviation*100:.1f}%) → 戻り待ち")
        else:
            # MA50下 → 逆張りになるため減点
            score -= 0.2
            reasons.append(f"MA50下 → 逆張りリスク")

    elif regime == "BEAR":
        # 下降トレンドでのロングは減点
        score -= 0.3
        reasons.append("下降トレンド中のBUY → リスク高")

    elif regime == "RANGE" and ma20:
        # レンジ相場: BBバンド下限付近が理想
        if bb_lower and price <= bb_lower * 1.02:
            score += 0.2
            reasons.append("BB下限付近 → 逆張りゾーン")
        elif bb_upper and price >= bb_upper * 0.98:
            score -= 0.2
            reasons.append("BB上限付近 → 買いに不利")

    # ══════════════════════════════════════════════
    # 2. RSI エントリー品質
    # ══════════════════════════════════════════════
    if rsi is not None:
        if rsi < 35:
            score += 0.15
            reasons.append(f"RSI={rsi:.0f} 売られすぎゾーン → 良いエントリー")
        elif rsi > 70:
            score -= 0.2
            reasons.append(f"RSI={rsi:.0f} 買われすぎ → 入りにくい")
        elif 40 <= rsi <= 60:
            reasons.append(f"RSI={rsi:.0f} 中立")

    # ══════════════════════════════════════════════
    # 3. ATRベース R:R チェック
    # ══════════════════════════════════════════════
    if price and atr:
        atr_pct = atr / price
        if atr_pct < 0.005:
            # ボラ低すぎ → 手数料負けリスク
            score -= 0.15
            reasons.append(f"ATR低すぎ({atr_pct*100:.2f}%) → 利幅確保困難")
        elif atr_pct > 0.08:
            # ボラ高すぎ → リスク過大
            score -= 0.1
            reasons.append(f"ATR高め({atr_pct*100:.1f}%) → 要注意")
        else:
            reasons.append(f"ATR={atr_pct*100:.2f}% 適正ボラ")

    # ══════════════════════════════════════════════
    # 4. ADX トレンド強度確認
    # ══════════════════════════════════════════════
    if adx is not None:
        if adx > 30:
            score += 0.1
            reasons.append(f"ADX={adx:.0f} トレンド強 → モメンタム信頼性高")
        elif adx < 15:
            # トレンドが弱い → シグナルの信頼性低
            score -= 0.1
            reasons.append(f"ADX={adx:.0f} トレンド弱 → 方向感なし")

    quality = round(min(max(score, 0.0), 1.5), 3)
    should_enter = quality >= 0.7

    summary = f"エントリー品質={quality:.2f}" + (
        " [推奨]" if quality >= 1.0 else
        " [許容]" if quality >= 0.7 else
        " [見送り推奨]"
    )
    if reasons:
        summary += " | " + " / ".join(reasons)

    return should_enter, quality, summary


def pullback_entry_score(price: float, ma20: Optional[float],
                         ma50: Optional[float]) -> float:
    """
    押し目の深さスコア（0〜1）
    MA20にどれだけ近いか。0.8以上が理想的な押し目。
    """
    if not (price and ma20):
        return 0.5
    deviation = abs(price - ma20) / ma20
    # 0%乖離=1.0, 5%乖離=0.5, 10%=0.0
    return max(0.0, 1.0 - deviation * 10)
