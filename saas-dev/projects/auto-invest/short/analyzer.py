"""
SHORT bot 分析モジュール — ML + LLM統合版

シグナル一覧:
  【従来】RSI / MACD / BB / F&G / ニュース
  【Phase1】ADXレジーム / MTF / ボラモメンタム / FR+OI / MACDヒスト
  【Phase3】MLPredictor(XGBoost) / LLMSentiment(Claude API)

意思決定:
  ルールスコア + MLスコア + LLMスコア → 統合判断
  「RSI=28かつFR=0.08かつADX=32のとき特に有効」をMLが自動発見
"""

from dataclasses import dataclass
from typing import Literal
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

Decision = Literal["BUY", "SELL", "HOLD"]


@dataclass
class Signal:
    name: str
    value: float
    score: int
    reason: str


class RuleBasedAnalyzer:

    def __init__(self):
        import sys
        from pathlib import Path as _Path
        sys.path.insert(0, str(_Path(__file__).parent.parent / "shared"))
        try:
            from learner import load_thresholds
            t = load_thresholds("SHORT")
        except Exception:
            t = {}
        self.RSI_OVERSOLD    = t.get("rsi_oversold",   30.0)
        self.RSI_OVERBOUGHT  = t.get("rsi_overbought", 70.0)
        self.FG_BUY          = t.get("fear_greed_buy",  25)
        self.FG_SELL         = t.get("fear_greed_sell", 75)
        self.NEWS_POS        = t.get("news_positive",    3)
        self.NEWS_NEG        = t.get("news_negative",   -3)
        self.BUY_THRESHOLD   = t.get("buy_threshold",   3)   # 閾値を+2→+3に引き上げ
        self.SELL_THRESHOLD  = t.get("sell_threshold", -3)
        self.SIGNAL_WEIGHTS  = t.get("signal_weights", {})

    def analyze(self, market_data: dict) -> dict:
        t    = market_data.get("technicals", {})
        fg   = market_data.get("fear_greed", {}) or {}
        ns   = market_data.get("news_sentiment", {})
        deriv = market_data.get("derivatives", {})

        signals = []
        price = t.get("current_price")

        # ══════════════════════════════════════════════
        # 【フィルター】ADXレジーム判定
        # ADX > 25 → トレンド相場: モメンタム系を優先
        # ADX < 20 → レンジ相場 : 逆張り系を優先
        # ══════════════════════════════════════════════
        adx      = t.get("adx")
        di_plus  = t.get("di_plus")
        di_minus = t.get("di_minus")
        is_trending = adx is not None and adx > 25
        is_range    = adx is not None and adx < 20

        if adx is not None:
            if adx > 30 and di_plus and di_minus:
                direction = "上昇" if di_plus > di_minus else "下降"
                score = +1 if di_plus > di_minus else -1
                signals.append(Signal("ADX", adx, score,
                    f"ADX={adx:.1f} 強トレンド({direction}) DI+={di_plus:.1f}/DI-={di_minus:.1f}"))
            elif adx < 20:
                signals.append(Signal("ADX", adx, 0,
                    f"ADX={adx:.1f} レンジ相場 → 逆張りシグナル優先"))

        # ══════════════════════════════════════════════
        # 【新規】マルチタイムフレーム確認
        # price > MA20 > MA50 → 上昇トレンド確認
        # ══════════════════════════════════════════════
        ma20 = t.get("ma20")
        ma50 = t.get("ma50")
        if price and ma20 and ma50:
            if price > ma20 and ma20 > ma50:
                signals.append(Signal("MTF", price, +1,
                    f"価格>${price:,.0f} > MA20=${ma20:,.0f} > MA50=${ma50:,.0f} → 上昇トレンド確認"))
            elif price < ma20 and ma20 < ma50:
                signals.append(Signal("MTF", price, -1,
                    f"価格${price:,.0f} < MA20${ma20:,.0f} < MA50${ma50:,.0f} → 下降トレンド確認"))
            else:
                signals.append(Signal("MTF", price, 0,
                    f"MA配列不整合（トレンド不明）"))

        # ══════════════════════════════════════════════
        # 【新規】ボラティリティ調整モメンタム
        # 研究実績: Sharpe+0.7、週次リターン+1.86〜2.4%
        # ══════════════════════════════════════════════
        vol_mom = t.get("vol_momentum")
        if vol_mom is not None:
            if vol_mom > 1.5:
                signals.append(Signal("VolMom", vol_mom, +1,
                    f"ボラ調整モメンタム={vol_mom:.2f} → 上昇モメンタム強"))
            elif vol_mom < -1.5:
                signals.append(Signal("VolMom", vol_mom, -1,
                    f"ボラ調整モメンタム={vol_mom:.2f} → 下降モメンタム強"))
            else:
                signals.append(Signal("VolMom", vol_mom, 0,
                    f"ボラ調整モメンタム={vol_mom:.2f} 中立"))

        # ══════════════════════════════════════════════
        # 【新規】ファンディングレート + OI
        # FR > 0.05%: ロングが過剰 → 下落リスク（逆張り売り圧力）
        # FR < 0.00%: ショートが過剰 → 上昇スクイーズリスク
        # ══════════════════════════════════════════════
        fr = deriv.get("funding_rate")
        oi = deriv.get("open_interest")
        ls_ratio = deriv.get("long_short_ratio")

        if fr is not None:
            fr_pct = fr * 100
            if fr_pct > 0.05:
                signals.append(Signal("FundingRate", fr_pct, -1,
                    f"FR={fr_pct:.3f}% 過熱（ロング過多）→ 下落リスク↑"))
            elif fr_pct < 0.00:
                signals.append(Signal("FundingRate", fr_pct, +1,
                    f"FR={fr_pct:.3f}% マイナス（ショート過多）→ スクイーズリスク"))
            else:
                signals.append(Signal("FundingRate", fr_pct, 0,
                    f"FR={fr_pct:.3f}% 中立"))

        if ls_ratio is not None:
            if ls_ratio > 1.8:
                signals.append(Signal("LSRatio", ls_ratio, -1,
                    f"L/S比={ls_ratio:.2f} ロング過多 → 下落圧力"))
            elif ls_ratio < 0.8:
                signals.append(Signal("LSRatio", ls_ratio, +1,
                    f"L/S比={ls_ratio:.2f} ショート過多 → スクイーズ可能性"))

        # ══════════════════════════════════════════════
        # 【強化】RSI + MACD 組み合わせ確認
        # 両方一致: スコア2倍の信頼性 (研究: Win Rate 50%→73%)
        # ══════════════════════════════════════════════
        rsi        = t.get("rsi")
        macd       = t.get("macd")
        macd_sig   = t.get("macd_signal")
        macd_hist  = t.get("macd_hist")
        macd_hist_prev = t.get("macd_hist_prev")

        rsi_score = macd_score = 0

        if rsi is not None:
            if rsi < self.RSI_OVERSOLD:
                rsi_score = +1
                signals.append(Signal("RSI", rsi, +1,
                    f"RSI={rsi:.1f} 売られすぎ → 反発期待"))
            elif rsi > self.RSI_OVERBOUGHT:
                rsi_score = -1
                signals.append(Signal("RSI", rsi, -1,
                    f"RSI={rsi:.1f} 買われすぎ → 過熱サイン"))
            else:
                signals.append(Signal("RSI", rsi, 0,
                    f"RSI={rsi:.1f} 中立"))

        if macd is not None and macd_sig is not None:
            if macd > macd_sig:
                macd_score = +1
                signals.append(Signal("MACD", macd, +1,
                    f"MACD>{macd_sig:.4f} 上昇クロス"))
            else:
                macd_score = -1
                signals.append(Signal("MACD", macd, -1,
                    f"MACD<{macd_sig:.4f} 下降クロス"))

        # MACDヒストグラム加速 (勢いの増減を捉える)
        if macd_hist is not None and macd_hist_prev is not None:
            if macd_hist > 0 and macd_hist > macd_hist_prev:
                signals.append(Signal("MACDHist", macd_hist, +1,
                    f"MACDヒスト加速({macd_hist_prev:.4f}→{macd_hist:.4f}) → 上昇勢い増加"))
            elif macd_hist < 0 and macd_hist < macd_hist_prev:
                signals.append(Signal("MACDHist", macd_hist, -1,
                    f"MACDヒスト加速({macd_hist_prev:.4f}→{macd_hist:.4f}) → 下降勢い増加"))

        # RSI+MACDが両方一致するボーナス
        if rsi_score != 0 and macd_score != 0 and rsi_score == macd_score:
            signals.append(Signal("RSI_MACD_Confirm", 1.0, rsi_score,
                f"RSI+MACD確認一致 → 信頼度ボーナス(研究:Win Rate 73%)"))

        # ── ボリンジャーバンド ────────────────────────────
        bb_upper = t.get("bb_upper")
        bb_lower = t.get("bb_lower")
        if price and bb_upper and bb_lower:
            band_width = bb_upper - bb_lower
            if price <= bb_lower:
                signals.append(Signal("BB", price, +1,
                    f"下限タッチ(${bb_lower:,.0f}) → 売られすぎ反発期待"))
            elif price >= bb_upper:
                signals.append(Signal("BB", price, -1,
                    f"上限タッチ(${bb_upper:,.0f}) → 買われすぎ"))
            elif band_width > 0:
                bb_pos = (price - bb_lower) / band_width
                signals.append(Signal("BB", price, 0,
                    f"バンド内({bb_pos:.0%}位置)"))

        # ── Fear & Greed ──────────────────────────────────
        fg_val = fg.get("value")
        if fg_val is not None:
            if fg_val <= self.FG_BUY:
                signals.append(Signal("FearGreed", fg_val, +1,
                    f"F&G={fg_val} 極端な恐怖 → 歴史的買い場"))
            elif fg_val >= self.FG_SELL:
                signals.append(Signal("FearGreed", fg_val, -1,
                    f"F&G={fg_val} 極端な強欲 → 過熱"))
            else:
                signals.append(Signal("FearGreed", fg_val, 0,
                    f"F&G={fg_val} 中立"))

        # ── ニュースセンチメント ───────────────────────────
        news_score = ns.get("score", 0)
        news_count = ns.get("count", 0)
        if news_count > 0:
            if news_score >= self.NEWS_POS:
                signals.append(Signal("News", news_score, +1,
                    f"ニュース強ポジティブ(+{news_score})"))
            elif news_score <= self.NEWS_NEG:
                signals.append(Signal("News", news_score, -1,
                    f"ニュース強ネガティブ({news_score})"))

        # ══════════════════════════════════════════════
        # 【Phase3】LLMセンチメント（Claude API）
        # キーワードより文脈・否定・重要度を理解
        # ══════════════════════════════════════════════
        llm_sent = market_data.get("llm_sentiment", {})
        if llm_sent:
            try:
                from llm_sentiment import sentiment_to_signal
                llm_score, llm_reason = sentiment_to_signal(llm_sent)
                signals.append(Signal("LLMSentiment", llm_sent.get("score", 0),
                                      llm_score, llm_reason))
            except Exception:
                pass

        # ══════════════════════════════════════════════
        # 【Phase3】MLPredictor (XGBoost)
        # 過去取引から「このシグナル組み合わせで勝てるか」を予測
        # データ不足時は中立(score=0)を返す
        # ══════════════════════════════════════════════
        try:
            from ml_predictor import get_predictor
            predictor = get_predictor("SHORT")
            ml_score, ml_reason = predictor.signal_score(
                [{"name": s.name, "score": s.score} for s in signals])
            if ml_score != 0:  # 中立なら追加しない
                signals.append(Signal("MLPredictor", 0.5, ml_score, ml_reason))
        except Exception:
            pass

        # ══════════════════════════════════════════════
        # スコア集計（学習済み重み適用）
        # ══════════════════════════════════════════════
        total_score = sum(
            s.score * self.SIGNAL_WEIGHTS.get(s.name, 1.0)
            for s in signals
        )

        # ── 低品質シグナルフィルター ──────────────────────
        # レンジ相場でトレンド系シグナルだけが出ている場合はHOLD
        if is_range and abs(total_score) < 4:
            # レンジ相場では逆張りシグナルが揃っていないと動かない
            total_score *= 0.5

        if total_score >= self.BUY_THRESHOLD:
            decision: Decision = "BUY"
            confidence = min(1.0, total_score / max(len(signals), 1))
        elif total_score <= self.SELL_THRESHOLD:
            decision = "SELL"
            confidence = min(1.0, abs(total_score) / max(len(signals), 1))
        else:
            decision = "HOLD"
            confidence = 0.5

        if abs(total_score) >= 6:
            risk_level = "LOW"
        elif abs(total_score) >= 3:
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"

        reasoning = self._build_reasoning(signals, total_score, decision)
        return {
            "decision":    decision,
            "confidence":  round(confidence, 2),
            "reasoning":   reasoning,
            "risk_level":  risk_level,
            "total_score": total_score,
            "signals":     [{"name": s.name, "score": s.score, "reason": s.reason}
                            for s in signals],
        }

    def _build_reasoning(self, signals, total_score, decision):
        lines = [f"合計スコア: {total_score:+.2f} → {decision}"]
        for s in signals:
            mark = "↑" if s.score > 0 else ("↓" if s.score < 0 else "→")
            lines.append(f"  {mark} {s.reason}")
        return " | ".join(lines)
