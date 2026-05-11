"""
LONG bot 分析モジュール — マクロ統合版

シグナル一覧:
  【従来】P/E / 売上成長 / 利益率 / 負債 / ROE / 52週高値 / マクロニュース / 総合スコア
  【新規】VIX / DXY / US10Y金利 / M2マネーサプライ / ボラモメンタム
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


class LongTermAnalyzer:

    def __init__(self):
        t = load_thresholds("LONG")
        self.BUY_THRESHOLD  = t["buy_threshold"]
        self.SELL_THRESHOLD = t["sell_threshold"]
        self.SIGNAL_WEIGHTS = t.get("signal_weights", {})

    def analyze(self, market_data: dict) -> dict:
        signals   = []
        scores    = market_data.get("scores", {})
        funds     = market_data.get("fundamentals", {})
        macro_n   = market_data.get("macro_news", {})
        macro_i   = market_data.get("macro_indicators", {})
        m2        = market_data.get("m2", {})
        primary   = market_data.get("primary_ticker", "AAPL")
        f         = funds.get(primary, {})

        # ══════════════════════════════════════════════
        # 【新規】マクロレジーム判定（最優先・環境フィルター）
        # ══════════════════════════════════════════════

        # VIX: 恐怖指数
        vix = macro_i.get("VIX", {})
        if vix:
            v = vix.get("value", 20)
            if v > 35:
                signals.append(Signal("VIX", -3,
                    f"VIX={v:.1f} 極度恐怖（>35）→ 長期も守り優先"))
            elif v > 25:
                signals.append(Signal("VIX", -1,
                    f"VIX={v:.1f} 警戒圏（25〜35）→ ポジションサイズ縮小"))
            elif v < 15:
                signals.append(Signal("VIX", +1,
                    f"VIX={v:.1f} 低ボラ（<15）→ リスクオン環境"))

        # US10Y: 金利環境（高金利は株式バリュエーションを圧迫）
        tnx = macro_i.get("US10Y", {})
        if tnx:
            v   = tnx.get("value", 4.0)
            trend = tnx.get("trend", "")
            if v > 5.0:
                signals.append(Signal("Rates", -2,
                    f"US10Y={v:.2f}% 高金利（>5%）→ 株式割高化 / 割引率上昇"))
            elif v > 4.5 and trend == "UP":
                signals.append(Signal("Rates", -1,
                    f"US10Y={v:.2f}% 上昇中 → バリュエーション圧迫"))
            elif v < 3.5 and trend == "DOWN":
                signals.append(Signal("Rates", +2,
                    f"US10Y={v:.2f}% 低下中 → 株式に好環境"))
            elif v < 4.0:
                signals.append(Signal("Rates", +1,
                    f"US10Y={v:.2f}% 低め → 許容範囲内"))

        # DXY: ドル強弱（ドル高は海外売上比率の高い大型株に逆風）
        dxy = macro_i.get("DXY", {})
        if dxy:
            v   = dxy.get("value", 100)
            chg = dxy.get("change_pct", 0)
            if chg > 1.0:
                signals.append(Signal("DXY", -1,
                    f"DXY={v:.1f} ドル急騰(+{chg:.1f}%) → 多国籍企業に逆風"))
            elif chg < -1.0:
                signals.append(Signal("DXY", +1,
                    f"DXY={v:.1f} ドル急落({chg:.1f}%) → 多国籍企業に追い風"))

        # M2マネーサプライ（流動性環境）
        # ※4年サイクル理論は崩壊。現在はM2が株式/BTCの主因
        if m2:
            yoy = m2.get("yoy_pct", 0)
            trend = m2.get("trend", "FLAT")
            if trend == "EXPANDING" and yoy > 5:
                signals.append(Signal("M2", +2,
                    f"M2 YoY={yoy:.1f}% 拡大中 → 流動性環境良好 / 資産価格に追い風"))
            elif trend == "EXPANDING":
                signals.append(Signal("M2", +1,
                    f"M2 YoY={yoy:.1f}% 緩やかに拡大"))
            elif trend == "CONTRACTING":
                signals.append(Signal("M2", -2,
                    f"M2 YoY={yoy:.1f}% 収縮中 → 流動性引き締め / 資産価格に逆風"))

        # ══════════════════════════════════════════════
        # ファンダメンタルズシグナル（従来）
        # ══════════════════════════════════════════════

        # P/E
        pe  = f.get("pe_ratio")
        fpe = f.get("forward_pe")
        if pe:
            if pe < 15:
                signals.append(Signal("PE", +2, f"PER={pe:.1f} 割安（<15）"))
            elif pe < 25:
                signals.append(Signal("PE", +1, f"PER={pe:.1f} 適正（15〜25）"))
            elif pe > 40:
                signals.append(Signal("PE", -2, f"PER={pe:.1f} 割高（>40）"))
            if fpe and fpe < pe * 0.8:
                signals.append(Signal("ForwardPE", +1,
                    f"予想PER={fpe:.1f} < 実績{pe:.1f} → 利益成長加速"))

        # 売上成長
        rg = f.get("revenue_growth")
        if rg is not None:
            if rg > 0.20:
                signals.append(Signal("Revenue", +2, f"売上成長={rg*100:.1f}% 高成長"))
            elif rg > 0.10:
                signals.append(Signal("Revenue", +1, f"売上成長={rg*100:.1f}% 成長継続"))
            elif rg < 0:
                signals.append(Signal("Revenue", -2, f"売上成長={rg*100:.1f}% 減収"))

        # 利益率
        margin = f.get("profit_margin")
        if margin:
            if margin > 0.20:
                signals.append(Signal("Margin", +1, f"利益率={margin*100:.1f}% 高収益"))
            elif margin < 0.05:
                signals.append(Signal("Margin", -1, f"利益率={margin*100:.1f}% 低収益"))

        # 負債比率
        dte = f.get("debt_to_equity")
        if dte is not None:
            if dte < 50:
                signals.append(Signal("Debt", +1, f"D/E={dte:.0f} 財務健全"))
            elif dte > 200:
                signals.append(Signal("Debt", -1, f"D/E={dte:.0f} 高負債"))

        # ROE
        roe = f.get("roe")
        if roe and roe > 0.15:
            signals.append(Signal("ROE", +1, f"ROE={roe*100:.1f}% 資本効率良好"))

        # 52週高値からの乖離
        from_high = f.get("from_52w_high")
        if from_high and from_high < -30:
            signals.append(Signal("Price", +1,
                f"高値から{from_high:.1f}% 下落 → 割安感"))

        # ボラティリティ調整モメンタム
        vol_mom = f.get("vol_momentum")
        if vol_mom is not None:
            if vol_mom > 1.5:
                signals.append(Signal("VolMom", +1,
                    f"ボラ調整モメンタム={vol_mom:.2f} → 上昇勢い確認"))
            elif vol_mom < -1.5:
                signals.append(Signal("VolMom", -1,
                    f"ボラ調整モメンタム={vol_mom:.2f} → 下降勢い"))

        # マクロニュース
        ms = macro_n.get("score", 0)
        if ms >= 3:
            signals.append(Signal("MacroNews", +2, f"マクロニュース強ポジティブ(+{ms})"))
        elif ms >= 1:
            signals.append(Signal("MacroNews", +1, f"マクロニュースやや強気(+{ms})"))
        elif ms <= -3:
            signals.append(Signal("MacroNews", -2, f"マクロニュース強ネガティブ({ms})"))
        elif ms <= -1:
            signals.append(Signal("MacroNews", -1, f"マクロニュースやや弱気({ms})"))

        # 総合ファンダスコア
        fund_score = scores.get(primary, 0)
        if fund_score >= 5:
            signals.append(Signal("Overall", +2, f"{primary} ファンダスコア={fund_score} 優良"))
        elif fund_score >= 3:
            signals.append(Signal("Overall", +1, f"{primary} ファンダスコア={fund_score} 良好"))
        elif fund_score <= 0:
            signals.append(Signal("Overall", -1, f"{primary} ファンダスコア={fund_score} 要注意"))

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
            predictor = get_predictor("LONG")
            ml_score, ml_reason = predictor.signal_score(
                [{"name": s.name, "score": s.score} for s in signals])
            if ml_score != 0:
                signals.append(Signal("MLPredictor", ml_score, ml_reason))
        except Exception:
            pass

        # スコア合算
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

        # マクロ環境が最悪な場合はBUYを抑制
        vix_val = vix.get("value", 20) if vix else 20
        m2_trend = m2.get("trend", "FLAT")
        if vix_val > 35 and m2_trend == "CONTRACTING":
            if decision == "BUY":
                decision = "HOLD"
                confidence = 0.3
                total = 0  # レポート用

        risk = "LOW" if abs(total) >= 6 else ("MEDIUM" if abs(total) >= 4 else "HIGH")
        reasoning = f"合計スコア:{total:+.1f} → {decision} | " + " | ".join(s.reason for s in signals)

        return {
            "decision":    decision,
            "confidence":  round(confidence, 2),
            "reasoning":   reasoning,
            "risk_level":  risk,
            "total_score": round(total, 2),
            "signals":     [{"name": s.name, "score": s.score, "reason": s.reason}
                            for s in signals],
            "recommended": primary,
        }
