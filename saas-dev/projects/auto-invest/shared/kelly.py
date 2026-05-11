"""
Kelly基準ポジションサイジング + ドローダウン管理
研究実績: Fractional Kelly(0.25) で期待値+50%向上
"""
from __future__ import annotations


class KellyCriterion:
    """
    フラクショナル・ケリー基準
    Full Kelly × fraction (デフォルト0.25) で過剰リスクを防ぐ
    """

    def __init__(self, fraction: float = 0.25):
        self.fraction = fraction  # Full Kellyの何割を使うか (0.25=保守的)

    def optimal_fraction(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Kelly公式: f* = (b*p - q) / b
          b = avg_win / avg_loss  (リワード/リスク比)
          p = 勝率
          q = 1 - p
        上限: 25% (過剰ベット防止)
        """
        if avg_loss <= 0 or win_rate <= 0:
            return 0.02  # データ不足時のフォールバック
        b = avg_win / avg_loss
        p = min(max(win_rate, 0.01), 0.99)
        q = 1.0 - p
        f_full = (b * p - q) / b
        f_full = max(0.0, f_full)           # 負のKelly(期待値マイナス)→ 0
        return min(self.fraction * f_full, 0.25)  # 最大25%キャップ

    @staticmethod
    def from_trade_history(trades: list[dict], lookback: int = 30) -> tuple[float, float, float]:
        """
        直近 lookback 件の確定トレードから (win_rate, avg_win, avg_loss) を計算
        trades: [{"action": "SELL", "pnl": float}, ...]
        """
        closed = [
            t for t in trades
            if t.get("action") in ("SELL", "BUY") and t.get("pnl") is not None
        ][-lookback:]
        if len(closed) < 5:
            # データ不足: デフォルト (勝率50%, R:R=1.5:1)
            return 0.50, 1.5, 1.0
        wins   = [t["pnl"] for t in closed if t["pnl"] > 0]
        losses = [abs(t["pnl"]) for t in closed if t["pnl"] <= 0]
        win_rate = len(wins) / len(closed)
        avg_win  = (sum(wins)   / len(wins))   if wins   else 1.0
        avg_loss = (sum(losses) / len(losses)) if losses else 1.0
        return win_rate, avg_win, avg_loss

    def position_size_usd(self, balance: float,
                          win_rate: float, avg_win: float, avg_loss: float,
                          min_pct: float = 0.05, max_pct: float = 0.25) -> float:
        """
        最適ポジションサイズ (USD)
        min_pct: 最低でもbalanceのmin_pct%は投資
        max_pct: 上限
        """
        frac = self.optimal_fraction(win_rate, avg_win, avg_loss)
        frac = max(frac, min_pct)   # 最低保証
        frac = min(frac, max_pct)   # 上限
        return balance * frac


class DrawdownManager:
    """
    3段階ドローダウン制御
    -10%: エクスポージャー75%(25%削減)
    -15%: エクスポージャー50%(50%削減)
    -20%: 新規エントリー停止 (0%)
    """

    STAGES = [
        (0.20, 0.00),  # -20% DD → 新規停止
        (0.15, 0.50),  # -15% DD → 半分のポジションサイズ
        (0.10, 0.75),  # -10% DD → 75%のポジションサイズ
    ]

    def __init__(self, initial_value: float):
        self.peak = initial_value

    def exposure_multiplier(self, current_value: float) -> float:
        """
        現在の資産でpeakを更新し、エクスポージャー乗数を返す
        1.0=通常 / 0.5=半分 / 0.0=停止
        """
        if current_value > self.peak:
            self.peak = current_value
        if self.peak <= 0:
            return 1.0
        dd = (self.peak - current_value) / self.peak
        for threshold, multiplier in self.STAGES:
            if dd >= threshold:
                return multiplier
        return 1.0

    def drawdown_pct(self, current_value: float) -> float:
        if self.peak <= 0:
            return 0.0
        return (self.peak - current_value) / self.peak * 100

    def status(self, current_value: float) -> str:
        dd = self.drawdown_pct(current_value)
        mult = self.exposure_multiplier(current_value)
        if mult == 0.0:
            return f"DD={dd:.1f}% 【新規エントリー停止】"
        elif mult < 1.0:
            return f"DD={dd:.1f}% 【エクスポージャー{mult*100:.0f}%に制限】"
        return f"DD={dd:.1f}% 正常"
