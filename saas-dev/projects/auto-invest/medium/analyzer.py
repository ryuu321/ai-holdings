"""
MEDIUM bot 分析モジュール — 拡張版

シグナル一覧:
  【従来】ゴールデン/デスクロス / MA位置 / RSI / SPY / F&G / ニュース
  【新規】ADXレジーム / ボラモメンタム / BTC-ETH統計的裁定
          VIX / DXY / 金利 / RSI+MACD確認一致
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

from dataclasses import dataclass
from typing import Literal
from learner import load_thresholds

Decision = Literal["BUY", "SELL", "HOLD"]


@dataclass
class Signal:
    name: str
    score: float
    reason: str


class MediumTermAnalyzer:

    def __init__(self):
        t = load_thresholds("MEDIUM")
        self.BUY_THRESHOLD  = t["buy_threshold"]
        self.SELL_THRESHOLD = t["sell_threshold"]
        self.SIGNAL_WEIGHTS = t.get("signal_weights", {})

    def analyze(self, market_data: dict) -> dict:
        signals  = []
        assets   = market_data.get("assets", {})
        primary  = market_data.get("primary_ticker", "BTC-USD")
        tech     = assets.get(primary, {})
        fg       = market_data.get("fear_greed", {}) or {}
        news     = market_data.get("news_sentiment", {})
        stat_arb = market_data.get("stat_arb", {})
        macro    = market_data.get("macro", {})

        # ══════════════════════════════════════════════
        # 【新規】ADXレジームフィルター
        # ══════════════════════════════════════════════
        adx      = tech.get("adx")
        di_plus  = tech.get("di_plus")
        di_minus = tech.get("di_minus")

        if adx is not None:
            if adx > 25 and di_plus and di_minus:
                direction = "上昇" if di_plus > di_minus else "下降"
                score = +1 if di_plus > di_minus else -1
                signals.append(Signal("ADX", score,
                    f"ADX={adx:.1f} 強トレンド({direction}) → 方向性明確"))
            elif adx < 20:
                signals.append(Signal("ADX", 0,
                    f"ADX={adx:.1f} レンジ相場 → トレンドフォロー無効"))

        # ── ゴールデンクロス / デスクロス ─────────────────
        if tech.get("golden_cross"):
            signals.append(Signal("GoldenCross", +2,
                f"{primary}: 50MA上抜け → ゴールデンクロス（強買い）"))
        elif tech.get("death_cross"):
            signals.append(Signal("DeathCross", -2,
                f"{primary}: 50MA下抜け → デスクロス（強売り）"))

        # ── MA位置 ─────────────────────────────────────
        if tech.get("above_ma200") is True:
            signals.append(Signal("AboveMA200", +1, "価格が200MA上 → 長期上昇トレンド"))
        elif tech.get("above_ma200") is False:
            signals.append(Signal("BelowMA200", -1, "価格が200MA下 → 長期下降トレンド"))

        if tech.get("above_ma50") is True:
            signals.append(Signal("AboveMA50", +1, "価格が50MA上 → 中期上昇トレンド"))
        elif tech.get("above_ma50") is False:
            signals.append(Signal("BelowMA50", -1, "価格が50MA下 → 中期下降トレンド"))

        # ══════════════════════════════════════════════
        # 【新規】ボラティリティ調整モメンタム
        # ══════════════════════════════════════════════
        vol_mom = tech.get("vol_momentum")
        if vol_mom is not None:
            if vol_mom > 1.5:
                signals.append(Signal("VolMom", +1,
                    f"ボラ調整モメンタム={vol_mom:.2f} → 上昇勢い確認"))
            elif vol_mom < -1.5:
                signals.append(Signal("VolMom", -1,
                    f"ボラ調整モメンタム={vol_mom:.2f} → 下降勢い確認"))

        # ══════════════════════════════════════════════
        # 【新規】BTC-ETH 統計的裁定シグナル
        # 研究実績: Sharpe 1.58〜2.45
        # ══════════════════════════════════════════════
        if stat_arb and primary in ("BTC-USD", "bitcoin"):
            z = stat_arb.get("z_score")
            sig = stat_arb.get("signal")
            if z is not None:
                if sig == "BTC_CHEAP":
                    signals.append(Signal("StatArb", +2,
                        f"BTC-ETH裁定: Zスコア={z:.2f} BTCが相対的に割安 → 買い優位"))
                elif sig == "BTC_EXPENSIVE":
                    signals.append(Signal("StatArb", -1,
                        f"BTC-ETH裁定: Zスコア={z:.2f} BTCが相対的に割高 → 割安化を待つ"))
                else:
                    signals.append(Signal("StatArb", 0,
                        f"BTC-ETH裁定: Zスコア={z:.2f} 中立域"))

        # ══════════════════════════════════════════════
        # 【新規】マクロ指標シグナル
        # ══════════════════════════════════════════════
        vix = macro.get("VIX", {})
        dxy = macro.get("DX_Y_NYB", {})
        tnx = macro.get("TNX", {})

        if vix:
            v = vix.get("value", 0)
            if v > 30:
                signals.append(Signal("VIX", -2,
                    f"VIX={v:.1f} 恐怖圏（>30）→ リスクオフ環境"))
            elif v > 20:
                signals.append(Signal("VIX", -1,
                    f"VIX={v:.1f} 警戒圏（20〜30）"))
            else:
                signals.append(Signal("VIX", +1,
                    f"VIX={v:.1f} 低恐怖（<20）→ リスクオン環境"))

        if dxy:
            chg = dxy.get("change_pct", 0)
            v   = dxy.get("value", 100)
            if chg > 0.5:
                signals.append(Signal("DXY", -1,
                    f"DXY={v:.1f} ドル急騰(+{chg:.1f}%) → クリプト/株に逆風"))
            elif chg < -0.5:
                signals.append(Signal("DXY", +1,
                    f"DXY={v:.1f} ドル急落({chg:.1f}%) → リスク資産に追い風"))

        if tnx:
            v   = tnx.get("value", 4.0)
            chg = tnx.get("change", 0)
            if v > 5.0:
                signals.append(Signal("Rates", -2,
                    f"US10Y={v:.2f}% 高金利（>5%）→ 株式バリュエーション圧迫"))
            elif v > 4.5:
                signals.append(Signal("Rates", -1,
                    f"US10Y={v:.2f}% 高め → 要注意"))
            elif v < 3.5:
                signals.append(Signal("Rates", +1,
                    f"US10Y={v:.2f}% 低金利 → リスク資産に好環境"))

        # ── RSI ──────────────────────────────────────
        rsi  = tech.get("rsi")
        macd = tech.get("macd")
        macd_sig = tech.get("macd_signal")
        rsi_score = macd_score = 0

        if rsi is not None:
            if rsi < 35:
                rsi_score = +1
                signals.append(Signal("RSI", +1, f"RSI={rsi:.1f} 売られすぎ（中期<35）"))
            elif rsi > 65:
                rsi_score = -1
                signals.append(Signal("RSI", -1, f"RSI={rsi:.1f} 買われすぎ（中期>65）"))
            else:
                signals.append(Signal("RSI", 0, f"RSI={rsi:.1f} 中立"))

        if macd is not None and macd_sig is not None:
            if macd > macd_sig:
                macd_score = +1
                signals.append(Signal("MACD", +1, f"MACD上抜け → 上昇モメンタム"))
            else:
                macd_score = -1
                signals.append(Signal("MACD", -1, f"MACD下抜け → 下降モメンタム"))

        # RSI+MACD確認ボーナス
        if rsi_score != 0 and macd_score != 0 and rsi_score == macd_score:
            signals.append(Signal("RSI_MACD_Confirm", rsi_score,
                f"RSI+MACD一致 → 信頼度ボーナス"))

        # ── S&P500トレンド ───────────────────────────
        spy = assets.get("SPY", {})
        if spy.get("above_ma50") is True:
            signals.append(Signal("SPY", +1, "S&P500が50MA上 → 市場全体上昇"))
        elif spy.get("above_ma50") is False:
            signals.append(Signal("SPY", -1, "S&P500が50MA下 → 市場全体下降"))

        # ── Fear & Greed ──────────────────────────────
        fg_val = fg.get("value")
        if fg_val is not None:
            if fg_val <= 30:
                signals.append(Signal("FearGreed", +1, f"F&G={fg_val} 恐怖圏"))
            elif fg_val >= 70:
                signals.append(Signal("FearGreed", -1, f"F&G={fg_val} 強欲圏"))

        # ── ニュース ─────────────────────────────────
        ns = news.get("score", 0)
        if ns >= 4:
            signals.append(Signal("News", +1, f"ニュース強ポジティブ(+{ns})"))
        elif ns <= -4:
            signals.append(Signal("News", -1, f"ニュース強ネガティブ({ns})"))

        # ── LLMセンチメント ──────────────────────────
        llm_sent = market_data.get("llm_sentiment", {})
        if llm_sent:
            try:
                from llm_sentiment import sentiment_to_signal
                llm_score, llm_reason = sentiment_to_signal(llm_sent)
                if llm_score != 0:
                    signals.append(Signal("LLMSentiment", llm_score, llm_reason))
            except Exception:
                pass

        # ── MLPredictor ──────────────────────────────
        try:
            from ml_predictor import get_predictor
            predictor = get_predictor("MEDIUM")
            ml_score, ml_reason = predictor.signal_score(
                [{"name": s.name, "score": s.score} for s in signals])
            if ml_score != 0:
                signals.append(Signal("MLPredictor", ml_score, ml_reason))
        except Exception:
            pass

        # ── スコア合算 ────────────────────────────────
        total = sum(
            s.score * self.SIGNAL_WEIGHTS.get(s.name, 1.0)
            for s in signals
        )

        if total >= self.BUY_THRESHOLD:
            decision: Decision = "BUY"
            confidence = min(1.0, total / max(len(signals), 1))
        elif total <= self.SELL_THRESHOLD:
            decision = "SELL"
            confidence = min(1.0, abs(total) / max(len(signals), 1))
        else:
            decision = "HOLD"
            confidence = 0.5

        risk = "LOW" if abs(total) >= 6 else ("MEDIUM" if abs(total) >= 3 else "HIGH")
        reasoning = (f"合計スコア:{total:+.1f} → {decision} | " +
                     " | ".join(s.reason for s in signals))

        return {
            "decision":    decision,
            "confidence":  round(confidence, 2),
            "reasoning":   reasoning,
            "risk_level":  risk,
            "total_score": total,
            "signals":     [{"name": s.name, "score": s.score, "reason": s.reason}
                            for s in signals],
        }
