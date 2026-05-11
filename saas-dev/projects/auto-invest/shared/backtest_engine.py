"""
バックテストエンジン

既存のアナライザー・ポートフォリオロジックをそのまま使い、
過去データで戦略を検証する。

使用例:
    from backtest_engine import BacktestEngine
    engine = BacktestEngine("SHORT")
    result = engine.run("2022-01-01", "2024-12-31")
    result.print_report()

検証可能なシグナル（履歴データあり）:
    RSI, MACD, ATR, MA20/50/200, ADX, DI+/DI-, VolMom, BB
    ゴールデン/デスクロス, 統計的裁定 (BTC-ETH)
    VIX, US10Y (yfinance 無料履歴あり)

除外シグナル（リアルタイムのみ / 履歴なし）:
    Fear & Greed → 中立50固定
    Funding Rate / OI → スキップ (空dict)
    FinBERT感情 → スキップ (None)
    MLPredictor → バックテスト中に蓄積した取引から都度学習

コスト:
    手数料: 片道0.1% (Binance Takerレート)
    スリッページ: 0.05% (保守的見積もり)
"""
from __future__ import annotations

import sys
import os
import json
import uuid
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

warnings.filterwarnings("ignore")

# shared へのパスを確保
_SHARED = Path(__file__).parent
_ROOT   = _SHARED.parent
sys.path.insert(0, str(_SHARED))

import yfinance as yf
from ta.trend import ADXIndicator, SMAIndicator, MACD as MACDIndicator
from ta.momentum import RSIIndicator
from ta.volatility import BollingerBands, AverageTrueRange


# ── 取引コスト定数 ──────────────────────────────────────────────
FEE_RATE   = 0.001   # 0.10%  (Binance taker)
SLIP_RATE  = 0.0005  # 0.05%  スリッページ


# ── レジーム別パラメータ ─────────────────────────────────────────
# BULL: price > MA200, DI+ > DI- (上昇トレンド確認)
# BEAR: price < MA200, DI- > DI+ (下降トレンド確認)
# RANGE: それ以外

_SHORT_PARAMS = {
    "BULL":  {"tp": 0.15, "tight_start": 0.10, "tight_trail": 0.04,
              "trail": 0.06, "sl": -0.08},
    "BEAR":  {"tp": 0.08, "tight_start": 0.05, "tight_trail": 0.02,
              "trail": 0.03, "sl": -0.05},
    "RANGE": {"tp": 0.10, "tight_start": 0.07, "tight_trail": 0.03,
              "trail": 0.04, "sl": -0.06},
}

# ATRベース乗数（entry_price * atr_pct * multiplier でTP/SL計算）
# tp_atr=2.0 → ATRの2倍上で利確  sl_atr=1.5 → ATRの1.5倍下で損切り
_SHORT_ATR_MULT = {
    "BULL":  {"tp_atr": 2.5, "sl_atr": 1.2, "trail_atr": 2.0},
    "BEAR":  {"tp_atr": 1.5, "sl_atr": 1.0, "trail_atr": 1.5},
    "RANGE": {"tp_atr": 2.0, "sl_atr": 1.2, "trail_atr": 1.8},
}

_MEDIUM_PARAMS = {
    # BULL: 広いラダーで大きなトレンドを捉える
    "BULL":  {"ladder": [(0.10, 0.25), (0.20, 0.25), (0.40, 1.0)],
              "sl": -0.12, "trail": 0.09},
    "BEAR":  {"ladder": [(0.05, 0.33), (0.10, 0.33), (0.15, 1.0)],
              "sl": -0.08, "trail": 0.06},
    "RANGE": {"ladder": [(0.07, 0.33), (0.12, 0.33), (0.20, 1.0)],
              "sl": -0.10, "trail": 0.07},
}


def _regime_from_row(row: pd.Series, price: float) -> str:
    """1バーのテクニカル指標からレジームを返す"""
    ma200   = float(row.get("ma200")   or 0)
    adx     = float(row.get("adx")     or 0)
    di_plus = float(row.get("di_plus") or 0)
    di_minus= float(row.get("di_minus")or 0)

    if ma200 <= 0:
        return "RANGE"
    above_ma200 = price > ma200 * 0.98

    if adx > 20 and di_plus > 0 and di_minus > 0:
        if di_plus > di_minus:
            return "BULL" if above_ma200 else "RANGE"
        else:
            return "BEAR" if not above_ma200 else "RANGE"
    return "BULL" if above_ma200 else "BEAR"

# ── TREND bot パラメータ ─────────────────────────────────────────
# MA200トレンドフォロー + デュアルモメンタム + ATRトレーリング
_TREND_PARAMS = {
    "exit_buffer":    0.97,   # MA200の3%下でEXIT（v1と同じ）
    "trail_stop":     0.15,   # ピークから-15%でEXIT（v1と同じ）
    "hard_stop":     -0.12,   # エントリー価格から-12%強制退場（常時有効・新規追加）
    "cooldown_days":  20,     # 退場後20日間は再エントリー禁止（whipsaw防止・新規追加）
    "rsi_entry_min":  45,     # RSI45以上（v1と同じ）
    "require_golden": False,  # MA50>MA200 不要（v1と同じ）
    "entry_buffer":   1.00,   # MA200上ならOK（v1と同じ）
    "invest_pct":     0.90,   # バランスの90%を投入
    "recheck_days":   7,      # 週次エントリー判断
}

# ── ダウンロード用ティッカー ────────────────────────────────────
_TICKERS = {
    "SHORT":  {"primary": "BTC-USD"},
    "MEDIUM": {"primary": "BTC-USD", "secondary": "ETH-USD"},
    "LONG":   {"primary": "BTC-USD"},
    "TREND":  {"primary": "BTC-USD"},
    "VOLT":   {"primary": "BTC-USD"},
    "ATTACK": {"primary": "BTC-USD"},
}

# ── ATTACK bot パラメータ ─────────────────────────────────────────
# 「負けてもいい、大きく勝つ」攻撃型トレンドフォロー
# 勝率40-50% / プロフィットファクター3倍超を目指す
_ATTACK_PARAMS = {
    "exit_buffer":    0.95,   # MA200の5%下でEXIT（v1より広い）
    "trail_stop":     0.25,   # ピークから-25%（大きなトレンドを逃さない）
    "rsi_entry_min":  40,     # RSI40以上（早めにエントリー）
    "invest_pct":     0.95,   # 95%フルインベスト
    "recheck_days":   7,      # 週次エントリー判断
}

# ── VOLT bot パラメータ ──────────────────────────────────────────
# ボラティリティターゲティング + デュアルモメンタム + MA200フィルター
# AQR / Bridgewater / Man Group が実際に使うアプローチを再現
_VOLT_PARAMS = {
    "target_vol":       0.30,  # 年率30%ボラをターゲット（ポジションサイズの軸）
    "vol_window":       21,    # 21日ローリングボラ
    "ma_period":        200,   # MA200トレンドフィルター
    "momentum_days":    252,   # 12ヶ月絶対モメンタム（デュアルモメンタム）
    "rebal_threshold":  0.05,  # 5%ドリフトでリバランス（頻繁な売買を防ぐ）
    "max_invest_pct":   0.95,  # 最大95%まで投入
    "recheck_days":     7,     # 週次リバランス判断
    # CPPI（元本保護）パラメータ
    "cppi_floor_pct":   0.80,  # 初期資金の80%を固定フロアに設定（最大損失20%に制限）
    "cppi_multiplier":  5.0,   # CPPI乗数（クッション × 5 = 最大投資額）
}
_MACRO_TICKERS = {"VIX": "^VIX", "US10Y": "^TNX"}


# ════════════════════════════════════════════════════════════════
#  テクニカル指標の計算
# ════════════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCV DataFrame に全テクニカル指標を追加して返す"""
    close = df["Close"].squeeze()
    high  = df["High"].squeeze()
    low   = df["Low"].squeeze()

    # RSI
    df["rsi"] = RSIIndicator(close=close, window=14).rsi()

    # MACD
    m = MACDIndicator(close=close, window_slow=26, window_fast=12, window_sign=9)
    df["macd"]       = m.macd()
    df["macd_signal"]= m.macd_signal()
    df["macd_hist"]  = m.macd_diff()

    # Moving Averages
    df["ma20"]  = SMAIndicator(close=close, window=20).sma_indicator()
    df["ma50"]  = SMAIndicator(close=close, window=50).sma_indicator()
    df["ma200"] = SMAIndicator(close=close, window=200).sma_indicator()

    # ATR
    df["atr"] = AverageTrueRange(
        high=high, low=low, close=close, window=14
    ).average_true_range()

    # Bollinger Bands
    bb = BollingerBands(close=close, window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()

    # ADX + DI
    adx = ADXIndicator(high=high, low=low, close=close, window=14)
    df["adx"]      = adx.adx()
    df["di_plus"]  = adx.adx_pos()
    df["di_minus"] = adx.adx_neg()

    # ボラティリティ調整モメンタム (14日)
    mom = close.pct_change(14)
    std = close.pct_change().rolling(14).std()
    df["vol_momentum"] = mom / (std + 1e-9)

    # クロス系
    df["golden_cross"] = (df["ma50"] > df["ma200"]) & (df["ma50"].shift(1) <= df["ma200"].shift(1))
    df["death_cross"]  = (df["ma50"] < df["ma200"]) & (df["ma50"].shift(1) >= df["ma200"].shift(1))
    df["above_ma50"]   = close > df["ma50"]
    df["above_ma200"]  = close > df["ma200"]

    # ボラティリティターゲティング用
    df["realized_vol"] = close.pct_change().rolling(21).std() * np.sqrt(252)  # 年率換算21日ボラ
    df["momentum_12m"] = close.pct_change(252)   # 12ヶ月絶対モメンタム

    return df


def compute_stat_arb(btc_close: pd.Series, eth_close: pd.Series,
                     window: int = 60) -> pd.Series:
    """BTC/ETH 比率の Z スコア (MEDIUM bot 用)"""
    ratio  = btc_close / eth_close
    mean   = ratio.rolling(window).mean()
    std    = ratio.rolling(window).std()
    return (ratio - mean) / (std + 1e-9)


# ════════════════════════════════════════════════════════════════
#  synthetic market_data ビルダー
# ════════════════════════════════════════════════════════════════

def _row_val(row: pd.Series, col: str):
    """NaN → None に変換"""
    v = row.get(col)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return float(v)


def make_short_market_data(row: pd.Series) -> dict:
    """SHORT bot 用 market_data を合成する (Fear&Greed / derivatives はスキップ)"""
    price = _row_val(row, "Close")
    return {
        "technicals": {
            "current_price": price,
            "rsi":           _row_val(row, "rsi"),
            "macd":          _row_val(row, "macd"),
            "macd_hist":     _row_val(row, "macd_hist"),
            "adx":           _row_val(row, "adx"),
            "di_plus":       _row_val(row, "di_plus"),
            "di_minus":      _row_val(row, "di_minus"),
            "ma20":          _row_val(row, "ma20"),
            "ma50":          _row_val(row, "ma50"),
            "atr":           _row_val(row, "atr"),
            "vol_momentum":  _row_val(row, "vol_momentum"),
            "bb_lower":      _row_val(row, "bb_lower"),
            "bb_upper":      _row_val(row, "bb_upper"),
        },
        "fear_greed":    {"value": 50},   # 中立固定
        "derivatives":   {},              # スキップ
        "llm_sentiment": None,            # スキップ
        "news":          [],
        "news_sentiment":{},
    }


def make_medium_market_data(btc_row: pd.Series, eth_row: Optional[pd.Series],
                             z_score: Optional[float],
                             vix_val: Optional[float],
                             tnx_val: Optional[float]) -> dict:
    """MEDIUM bot 用 market_data を合成する"""
    btc_price = _row_val(btc_row, "Close")
    eth_price = _row_val(eth_row, "Close") if eth_row is not None else None

    btc_tech = {
        "price":        btc_price,
        "rsi":          _row_val(btc_row, "rsi"),
        "macd":         _row_val(btc_row, "macd"),
        "macd_hist":    _row_val(btc_row, "macd_hist"),
        "adx":          _row_val(btc_row, "adx"),
        "di_plus":      _row_val(btc_row, "di_plus"),
        "di_minus":     _row_val(btc_row, "di_minus"),
        "ma20":         _row_val(btc_row, "ma20"),
        "ma50":         _row_val(btc_row, "ma50"),
        "atr":          _row_val(btc_row, "atr"),
        "vol_momentum": _row_val(btc_row, "vol_momentum"),
        "golden_cross": bool(btc_row.get("golden_cross", False)),
        "death_cross":  bool(btc_row.get("death_cross", False)),
        "above_ma50":   bool(btc_row.get("above_ma50", False)),
        "above_ma200":  bool(btc_row.get("above_ma200", False)),
    }

    assets = {"BTC-USD": btc_tech}
    if eth_price:
        assets["ETH-USD"] = {"price": eth_price}

    stat_arb = {}
    if z_score is not None:
        if z_score > 2.0:
            sig = "BTC_EXPENSIVE"
        elif z_score < -2.0:
            sig = "BTC_CHEAP"
        else:
            sig = "NEUTRAL"
        stat_arb = {"z_score": round(z_score, 3), "signal": sig}

    macro = {}
    if vix_val is not None:
        macro["VIX"] = {"value": vix_val}
    if tnx_val is not None:
        macro["TNX"] = {"value": tnx_val}

    return {
        "assets":         assets,
        "primary_ticker": "BTC-USD",
        "stat_arb":       stat_arb,
        "macro":          macro,
        "fear_greed":     {"value": 50},
        "news_sentiment": {},
        "llm_sentiment":  None,
    }


# ════════════════════════════════════════════════════════════════
#  BacktestResult — 指標計算 + レポート出力
# ════════════════════════════════════════════════════════════════

@dataclass
class TradeEntry:
    date:          str
    action:        str
    price:         float
    shares:        float
    value_usd:     float
    fee_usd:       float
    pnl:           float
    balance_after: float
    reason:        str


@dataclass
class BacktestResult:
    bot_type:        str
    start_date:      str
    end_date:        str
    initial_balance: float
    equity_curve:    list   # [(date_str, equity)]
    trades:          list   # [TradeEntry]
    bh_curve:        list   # Buy-and-Hold baseline [(date_str, equity)]

    # ── 基本指標 ──────────────────────────────────────────────

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else self.initial_balance

    @property
    def total_return(self) -> float:
        return (self.final_equity / self.initial_balance) - 1

    @property
    def cagr(self) -> float:
        days = max(1, (pd.Timestamp(self.end_date) - pd.Timestamp(self.start_date)).days)
        return (self.final_equity / self.initial_balance) ** (365 / days) - 1

    @property
    def bh_cagr(self) -> float:
        if not self.bh_curve:
            return 0.0
        bh_final = self.bh_curve[-1][1]
        days = max(1, (pd.Timestamp(self.end_date) - pd.Timestamp(self.start_date)).days)
        return (bh_final / self.initial_balance) ** (365 / days) - 1

    @property
    def sharpe(self) -> float:
        equities = [e for _, e in self.equity_curve]
        returns  = pd.Series(equities).pct_change().dropna()
        if len(returns) < 2 or returns.std() == 0:
            return 0.0
        return (returns.mean() / returns.std()) * (252 ** 0.5)

    @property
    def sortino(self) -> float:
        equities = [e for _, e in self.equity_curve]
        returns  = pd.Series(equities).pct_change().dropna()
        downside = returns[returns < 0]
        if len(downside) == 0 or downside.std() == 0:
            return 99.0
        return (returns.mean() / downside.std()) * (252 ** 0.5)

    @property
    def max_drawdown(self) -> float:
        equities = [e for _, e in self.equity_curve]
        peak     = equities[0]
        max_dd   = 0.0
        for e in equities:
            if e > peak:
                peak = e
            dd = (peak - e) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def calmar(self) -> float:
        dd = self.max_drawdown
        return self.cagr / dd if dd > 0 else 99.0

    @property
    def win_rate(self) -> float:
        sells = [t for t in self.trades if t.action == "SELL" and t.pnl != 0]
        if not sells:
            return 0.0
        return len([t for t in sells if t.pnl > 0]) / len(sells)

    @property
    def profit_factor(self) -> float:
        sells = [t for t in self.trades if t.action == "SELL"]
        gross_p = sum(t.pnl for t in sells if t.pnl > 0)
        gross_l = abs(sum(t.pnl for t in sells if t.pnl < 0))
        return gross_p / gross_l if gross_l > 0 else 99.0

    @property
    def total_fees(self) -> float:
        return sum(t.fee_usd for t in self.trades)

    @property
    def total_trades(self) -> int:
        return len([t for t in self.trades if t.action in ("BUY", "SELL")])

    # ── 出力 ─────────────────────────────────────────────────

    def print_report(self):
        bh_str = f"{self.bh_cagr*100:+.1f}%" if self.bh_curve else "N/A"
        alpha  = (self.cagr - self.bh_cagr) * 100 if self.bh_curve else 0

        print()
        print("=" * 60)
        print(f"  バックテスト結果 [{self.bot_type}]")
        print("=" * 60)
        print(f"  期間         : {self.start_date} → {self.end_date}")
        print(f"  初期資金     : ${self.initial_balance:>10,.2f}")
        print(f"  最終資産     : ${self.final_equity:>10,.2f}")
        sign = "+" if self.total_return >= 0 else ""
        print(f"  総リターン   : {sign}{self.total_return*100:.1f}%")
        print()
        print(f"  ── リスク調整済みリターン ──")
        print(f"  CAGR         : {self.cagr*100:+.1f}%/年")
        print(f"  BH CAGR      : {bh_str}/年  (バイ&ホールド比較)")
        print(f"  Alpha        : {alpha:+.1f}%/年")
        print(f"  シャープ比   : {self.sharpe:.2f}")
        print(f"  ソルティノ比 : {self.sortino:.2f}")
        print(f"  カルマー比   : {self.calmar:.2f}")
        print(f"  最大DD       : {self.max_drawdown*100:.1f}%")
        print()
        print(f"  ── 取引統計 ──")
        print(f"  総取引数     : {self.total_trades}回")
        print(f"  勝率         : {self.win_rate*100:.1f}%")
        print(f"  プロフィット : {self.profit_factor:.2f}x")
        print(f"  支払手数料   : ${self.total_fees:,.2f}")
        print("=" * 60)

        # 取引履歴（最後の15件）
        sell_trades = [t for t in self.trades if t.action == "SELL"][-15:]
        if sell_trades:
            print("\n  最近の取引 (SELL):")
            for t in sell_trades:
                sign = "+" if t.pnl >= 0 else ""
                print(f"    {t.date[:10]}  ${t.price:>9,.0f}  "
                      f"PnL={sign}${t.pnl:>7.2f}  残高=${t.balance_after:,.2f}")

    def save_json(self, path: str):
        """結果をJSONファイルに保存"""
        data = {
            "bot_type":    self.bot_type,
            "start_date":  self.start_date,
            "end_date":    self.end_date,
            "metrics": {
                "initial_balance": self.initial_balance,
                "final_equity":    round(self.final_equity, 2),
                "total_return_pct": round(self.total_return * 100, 2),
                "cagr_pct":         round(self.cagr * 100, 2),
                "bh_cagr_pct":      round(self.bh_cagr * 100, 2),
                "sharpe":           round(self.sharpe, 3),
                "sortino":          round(self.sortino, 3),
                "calmar":           round(self.calmar, 3),
                "max_drawdown_pct": round(self.max_drawdown * 100, 2),
                "win_rate_pct":     round(self.win_rate * 100, 1),
                "profit_factor":    round(self.profit_factor, 3),
                "total_trades":     self.total_trades,
                "total_fees_usd":   round(self.total_fees, 2),
            },
            "equity_curve": self.equity_curve,
            "trades": [
                {
                    "date":          t.date,
                    "action":        t.action,
                    "price":         t.price,
                    "shares":        round(t.shares, 8),
                    "value_usd":     round(t.value_usd, 2),
                    "fee_usd":       round(t.fee_usd, 4),
                    "pnl":           round(t.pnl, 2),
                    "balance_after": round(t.balance_after, 2),
                }
                for t in self.trades
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  [保存] {path}")

    def plot(self, save_path: Optional[str] = None):
        """エクイティカーブをプロット"""
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates

            dates_eq  = [pd.Timestamp(d) for d, _ in self.equity_curve]
            equity    = [e for _, e in self.equity_curve]

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8),
                                            gridspec_kw={"height_ratios": [3, 1]})
            fig.suptitle(f"Backtest [{self.bot_type}]  "
                         f"CAGR={self.cagr*100:+.1f}%  Sharpe={self.sharpe:.2f}  "
                         f"MaxDD={self.max_drawdown*100:.1f}%",
                         fontsize=12)

            # エクイティカーブ
            ax1.plot(dates_eq, equity, color="#2196F3", linewidth=1.5, label="Strategy")
            if self.bh_curve:
                dates_bh = [pd.Timestamp(d) for d, _ in self.bh_curve]
                bh_vals  = [e for _, e in self.bh_curve]
                ax1.plot(dates_bh, bh_vals, color="#9E9E9E", linewidth=1,
                         linestyle="--", label="Buy & Hold")
            ax1.set_ylabel("Portfolio Value ($)")
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

            # ドローダウン
            peak  = pd.Series(equity).cummax()
            dd    = (pd.Series(equity) - peak) / peak * 100
            ax2.fill_between(dates_eq, dd, 0, color="#F44336", alpha=0.4)
            ax2.set_ylabel("Drawdown (%)")
            ax2.set_xlabel("Date")
            ax2.grid(True, alpha=0.3)
            ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))

            plt.tight_layout()
            if save_path:
                plt.savefig(save_path, dpi=150, bbox_inches="tight")
                print(f"  [グラフ保存] {save_path}")
            else:
                plt.show()
            plt.close()
        except ImportError:
            print("  [!] matplotlib未インストール。pip install matplotlib でグラフ表示可能")


# ════════════════════════════════════════════════════════════════
#  BacktestEngine
# ════════════════════════════════════════════════════════════════

class BacktestEngine:
    """
    既存ボットロジックを使って過去データを検証するエンジン。
    ルックアヘッドバイアスなし（各バー時点で利用可能なデータのみ使用）。
    """

    def __init__(self, bot_type: str, initial_balance: float = 10_000.0):
        self.bot_type        = bot_type.upper()
        self.initial_balance = initial_balance
        self._data_cache: dict[str, pd.DataFrame] = {}

    # ── データ取得 ────────────────────────────────────────────

    def _download(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        key = f"{ticker}_{start}_{end}"
        if key in self._data_cache:
            return self._data_cache[key]
        print(f"  [DL] {ticker}  {start} → {end} ...", end=" ", flush=True)
        df = yf.download(ticker, start=start, end=end,
                         auto_adjust=True, progress=False)
        if df.empty:
            print("データなし")
            return pd.DataFrame()
        # MultiIndex を解除
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open","High","Low","Close","Volume"]].copy()
        df = df.dropna(subset=["Close"])
        print(f"{len(df)}行")
        self._data_cache[key] = df
        return df

    def _download_macro(self, start: str, end: str) -> dict[str, pd.Series]:
        macro = {}
        for name, ticker in _MACRO_TICKERS.items():
            df = self._download(ticker, start, end)
            if not df.empty:
                macro[name] = df["Close"].squeeze()
        return macro

    # ── バックテスト本体 ──────────────────────────────────────

    def run(self, start: str = "2022-01-01", end: str = "2024-12-31",
            interval: str = "1d") -> BacktestResult:
        print(f"\n[BacktestEngine] {self.bot_type}  {start} → {end}  interval={interval}")
        print(f"  初期資金=${self.initial_balance:,.0f}  手数料={FEE_RATE*100:.2f}%  "
              f"スリッページ={SLIP_RATE*100:.3f}%")

        if self.bot_type == "SHORT":
            if interval == "1h":
                return self._run_short_hourly(start, end)
            return self._run_short(start, end)
        elif self.bot_type == "MEDIUM":
            return self._run_medium(start, end)
        elif self.bot_type == "TREND":
            return self._run_trend_follow(start, end)
        elif self.bot_type == "VOLT":
            return self._run_volt(start, end)
        elif self.bot_type == "ATTACK":
            return self._run_attack(start, end)
        else:
            print(f"  [!] {self.bot_type} は現在未対応。SHORT / MEDIUM / TREND / VOLT に対応")
            return self._run_short(start, end)

    def _run_short(self, start: str, end: str) -> BacktestResult:
        # データ取得
        # ウォームアップ期間を確保するために少し早めに取得
        import datetime
        start_dt  = pd.Timestamp(start) - pd.Timedelta(days=250)
        start_ext = start_dt.strftime("%Y-%m-%d")

        btc = self._download("BTC-USD", start_ext, end)
        if btc.empty:
            raise ValueError("BTC-USD データ取得失敗")

        btc = compute_indicators(btc)

        # アナライザーを動的インポート
        sys.path.insert(0, str(_ROOT / "short"))
        from analyzer import RuleBasedAnalyzer  # type: ignore
        analyzer = RuleBasedAnalyzer()

        # Kelly
        from kelly import KellyCriterion, DrawdownManager
        kelly   = KellyCriterion(fraction=0.25)
        dd_mgr  = DrawdownManager(self.initial_balance)

        # エントリー最適化
        from entry_optimizer import check_entry_quality

        # シミュレーション状態
        balance        = self.initial_balance
        position       = None    # {"price": float, "shares": float, "peak": float}
        trades: list[TradeEntry] = []
        equity_curve   = []
        bh_start_price = None
        bh_curve       = []

        # バックテスト期間のみループ
        bt_df = btc.loc[start:]
        if bt_df.empty:
            raise ValueError(f"{start} 以降のデータなし")

        print(f"  シミュレーション開始: {len(bt_df)} bars")

        for i, (date, row) in enumerate(bt_df.iterrows()):
            price = row.get("Close")
            if price is None or np.isnan(price):
                continue
            price = float(price)

            # Buy-and-Hold ベースライン
            if bh_start_price is None:
                bh_start_price = price
            bh_eq = self.initial_balance * (price / bh_start_price)
            bh_curve.append((str(date.date()), round(bh_eq, 2)))

            # 現在エクイティ
            pos_val = (position["shares"] * price) if position else 0.0
            equity  = balance + pos_val

            # ── 出口チェック（保有中のみ）─────────────────────
            if position:
                # トレーリングストップ更新
                if price > position["peak"]:
                    position["peak"] = price

                change_pct  = (price - position["price"]) / position["price"]
                trailing_dd = (position["peak"] - price) / position["peak"]
                regime_key  = position.get("regime", "RANGE")

                # ATRベース出口: エントリー時のATRをパーセントで算出
                atr_pct = position.get("atr_pct", None)
                if atr_pct and atr_pct > 0:
                    am = _SHORT_ATR_MULT[regime_key]
                    tp_pct    = atr_pct * am["tp_atr"]
                    sl_pct    = -atr_pct * am["sl_atr"]
                    trail_pct = atr_pct * am["trail_atr"]
                    # 上限・下限クリップ（極端な値を防ぐ）
                    tp_pct    = min(max(tp_pct, 0.06), 0.25)
                    sl_pct    = max(min(sl_pct, -0.04), -0.12)
                    trail_pct = min(max(trail_pct, 0.03), 0.12)
                else:
                    # ATRなし → 固定パラメータ
                    p = _SHORT_PARAMS[regime_key]
                    tp_pct    = p["tp"]
                    sl_pct    = p["sl"]
                    trail_pct = p["trail"]

                should_exit = False
                exit_reason = ""

                if change_pct >= tp_pct:
                    should_exit = True
                    exit_reason = f"利確+{change_pct*100:.1f}%"
                elif trailing_dd >= trail_pct:
                    should_exit = True
                    exit_reason = f"トレーリング-{trailing_dd*100:.1f}%"
                elif change_pct <= sl_pct:
                    should_exit = True
                    exit_reason = f"損切り{change_pct*100:.1f}%"

                if should_exit:
                    sell_price  = price * (1 - SLIP_RATE)
                    proceeds    = position["shares"] * sell_price
                    fee         = proceeds * FEE_RATE
                    pnl         = proceeds - fee - position["cost"]
                    balance    += proceeds - fee
                    trades.append(TradeEntry(
                        date=str(date.date()), action="SELL",
                        price=round(sell_price, 2),
                        shares=position["shares"],
                        value_usd=round(proceeds, 2),
                        fee_usd=round(fee, 4),
                        pnl=round(pnl, 2),
                        balance_after=round(balance, 2),
                        reason=exit_reason,
                    ))
                    position = None
                    equity   = balance

            # ── エントリー判断（ポジションなし時）────────────
            if position is None:
                market_data = make_short_market_data(row)
                analysis    = analyzer.analyze(market_data)
                decision    = analysis["decision"]

                if decision == "BUY":
                    # エントリー品質チェック
                    t = market_data["technicals"]
                    adx_v    = t.get("adx") or 0
                    di_plus  = t.get("di_plus") or 0
                    di_minus = t.get("di_minus") or 0
                    if adx_v > 25:
                        regime = "BULL" if di_plus > di_minus else "BEAR"
                    elif t.get("ma50") and price:
                        regime = "BULL" if price > (t.get("ma50") or 0) else "BEAR"
                    else:
                        regime = "RANGE"

                    should_enter, eq_score, _ = check_entry_quality(t, regime)

                    if should_enter:
                        # Kelly サイジング
                        recent_sells  = [t for t in trades if t.action == "SELL"]
                        win_rate_bt   = (
                            len([t for t in recent_sells[-30:] if t.pnl > 0]) /
                            max(len(recent_sells[-30:]), 1)
                        )
                        avg_win_bt  = (
                            np.mean([t.pnl for t in recent_sells[-30:] if t.pnl > 0])
                            if any(t.pnl > 0 for t in recent_sells[-30:]) else 150
                        )
                        avg_loss_bt = (
                            abs(np.mean([t.pnl for t in recent_sells[-30:] if t.pnl < 0]))
                            if any(t.pnl < 0 for t in recent_sells[-30:]) else 100
                        )

                        pv      = equity
                        dd_mult = dd_mgr.exposure_multiplier(pv)
                        invest  = kelly.position_size_usd(
                            balance, win_rate_bt, avg_win_bt, avg_loss_bt
                        ) * dd_mult
                        invest  = min(invest, balance * 0.95)

                        if invest > 100 and dd_mult > 0:
                            buy_price    = price * (1 + SLIP_RATE)
                            fee          = invest * FEE_RATE
                            shares       = (invest - fee) / buy_price
                            cost         = invest  # 取得コスト（手数料込み）
                            entry_regime = _regime_from_row(row, price)
                            atr_val      = float(t.get("atr") or 0)
                            atr_pct      = (atr_val / price) if price > 0 else 0
                            balance     -= invest
                            position     = {
                                "price":    buy_price,
                                "shares":   shares,
                                "peak":     buy_price,
                                "cost":     cost,
                                "regime":   entry_regime,
                                "atr_pct":  atr_pct,
                            }
                            trades.append(TradeEntry(
                                date=str(date.date()), action="BUY",
                                price=round(buy_price, 2),
                                shares=round(shares, 8),
                                value_usd=round(invest, 2),
                                fee_usd=round(fee, 4),
                                pnl=0.0,
                                balance_after=round(balance, 2),
                                reason=analysis["reasoning"][:80],
                            ))
                            equity = balance + shares * price

            equity_curve.append((str(date.date()), round(equity, 2)))

        # 未決済ポジションを最終価格でクローズ
        if position and bt_df is not None and not bt_df.empty:
            last_price = float(bt_df.iloc[-1]["Close"])
            sell_price = last_price * (1 - SLIP_RATE)
            proceeds   = position["shares"] * sell_price
            fee        = proceeds * FEE_RATE
            pnl        = proceeds - fee - position["cost"]
            balance   += proceeds - fee
            last_date  = str(bt_df.index[-1].date())
            trades.append(TradeEntry(
                date=last_date, action="SELL",
                price=round(sell_price, 2),
                shares=position["shares"],
                value_usd=round(proceeds, 2),
                fee_usd=round(fee, 4),
                pnl=round(pnl, 2),
                balance_after=round(balance, 2),
                reason="バックテスト終了 → 強制クローズ",
            ))
            equity_curve[-1] = (last_date, round(balance, 2))

        return BacktestResult(
            bot_type=self.bot_type,
            start_date=start,
            end_date=end,
            initial_balance=self.initial_balance,
            equity_curve=equity_curve,
            trades=trades,
            bh_curve=bh_curve,
        )

    def _run_trend_follow(self, start: str, end: str) -> BacktestResult:
        """
        MA200トレンドフォロー戦略（TREND bot）

        プロの手法を組み合わせた「下落を避けて上昇だけ取る」設計：
        1. MA200フィルター  : 価格 > MA200 → ホールド / 価格 < MA200*0.97 → キャッシュ
        2. RSIモメンタム確認 : RSI≥45で入場（弱いリバウンドは無視）
        3. デュアルモメンタム: MACD > 0 も確認（トレンド強度の二重確認）
        4. ATRトレーリング  : ピークから-15%で強制出口（急落対策）
        5. 週次判断        : 毎週月曜のみ売買判断（ノイズと手数料を最小化）
        """
        p = _TREND_PARAMS
        start_ext = (pd.Timestamp(start) - pd.Timedelta(days=250)).strftime("%Y-%m-%d")

        btc = self._download("BTC-USD", start_ext, end)
        if btc.empty:
            raise ValueError("BTC-USD データ取得失敗")
        btc = compute_indicators(btc)

        balance            = self.initial_balance
        position           = None   # {"price", "shares", "cost", "peak"}
        trades: list[TradeEntry] = []
        equity_curve       = []
        bh_curve           = []
        bh_start           = None
        last_decision_date = None
        cooldown_until     = pd.Timestamp("2000-01-01")  # 初回は即エントリー可

        bt_df = btc.loc[start:]
        if bt_df.empty:
            raise ValueError(f"{start} 以降のデータなし")

        print(f"  シミュレーション開始: {len(bt_df)} bars  (MA200トレンドフォロー v4)")
        print(f"  条件: entry>MA200 RSI>={p['rsi_entry_min']} / "
              f"exit<MA200*{p['exit_buffer']} trail-{p['trail_stop']*100:.0f}% "
              f"hard-{abs(p['hard_stop'])*100:.0f}% / クールダウン{p['cooldown_days']}日")

        for date, row in bt_df.iterrows():
            price = float(row["Close"])
            if np.isnan(price):
                continue

            # B&H
            if bh_start is None:
                bh_start = price
            bh_curve.append((str(date.date()),
                              round(self.initial_balance * price / bh_start, 2)))

            pos_val = (position["shares"] * price) if position else 0.0
            equity  = balance + pos_val

            # ── EXIT判断（毎日チェック）──────────────────────────
            if position:
                if price > position["peak"]:
                    position["peak"] = price

                change_pct  = (price - position["price"]) / position["price"]
                trailing_dd = (position["peak"] - price) / position["peak"]
                ma200_val   = float(row.get("ma200") or 0)

                hard_exit  = change_pct <= p["hard_stop"]
                ma_exit    = (ma200_val > 0) and (price < ma200_val * p["exit_buffer"])
                trail_exit = trailing_dd >= p["trail_stop"]

                if hard_exit or ma_exit or trail_exit:
                    if hard_exit:
                        exit_reason = f"ハードストップ{change_pct*100:.1f}%"
                    elif ma_exit:
                        exit_reason = f"MA200割れ ({price:.0f} < {ma200_val*p['exit_buffer']:.0f})"
                    else:
                        exit_reason = f"トレーリング -{trailing_dd*100:.1f}%"
                    sell_price     = price * (1 - SLIP_RATE)
                    proceeds       = position["shares"] * sell_price
                    fee            = proceeds * FEE_RATE
                    pnl            = proceeds - fee - position["cost"]
                    balance       += proceeds - fee
                    cooldown_until = date + pd.Timedelta(days=p["cooldown_days"])
                    trades.append(TradeEntry(
                        date=str(date.date()), action="SELL",
                        price=round(sell_price, 2),
                        shares=position["shares"],
                        value_usd=round(proceeds, 2),
                        fee_usd=round(fee, 4),
                        pnl=round(pnl, 2),
                        balance_after=round(balance, 2),
                        reason=exit_reason,
                    ))
                    position = None
                    equity   = balance

            # ── 週次エントリー判断 ────────────────────────────────
            is_weekly   = (last_decision_date is None or
                           (date - last_decision_date).days >= p["recheck_days"])
            in_cooldown = date < cooldown_until

            if position is None and is_weekly and not in_cooldown:
                last_decision_date = date
                ma200_val = float(row.get("ma200") or 0)
                ma50_val  = float(row.get("ma50")  or 0)
                rsi_val   = float(row.get("rsi")   or 0)
                macd_hist = float(row.get("macd_hist") or 0)

                above_ma200 = (ma200_val > 0) and (price > ma200_val * p["entry_buffer"])
                golden_ok   = (not p["require_golden"]) or (ma50_val >= ma200_val > 0)
                rsi_ok      = rsi_val >= p["rsi_entry_min"]
                macd_ok     = macd_hist > 0

                if above_ma200 and golden_ok and rsi_ok and macd_ok:
                    invest     = balance * p["invest_pct"]
                    buy_price  = price * (1 + SLIP_RATE)
                    fee        = invest * FEE_RATE
                    shares     = (invest - fee) / buy_price
                    balance   -= invest
                    position   = {
                        "price":  buy_price,
                        "shares": shares,
                        "cost":   invest,
                        "peak":   buy_price,
                    }
                    trades.append(TradeEntry(
                        date=str(date.date()), action="BUY",
                        price=round(buy_price, 2),
                        shares=round(shares, 8),
                        value_usd=round(invest, 2),
                        fee_usd=round(fee, 4),
                        pnl=0.0,
                        balance_after=round(balance, 2),
                        reason=f"MA200上 RSI={rsi_val:.0f} MACD上",
                    ))
                    equity = balance + shares * price

            equity_curve.append((str(date.date()), round(equity, 2)))

        # 最終クローズ
        if position and not bt_df.empty:
            last_price = float(bt_df.iloc[-1]["Close"])
            sell_price = last_price * (1 - SLIP_RATE)
            proceeds   = position["shares"] * sell_price
            fee        = proceeds * FEE_RATE
            pnl        = proceeds - fee - position["cost"]
            balance   += proceeds - fee
            last_date  = str(bt_df.index[-1].date())
            trades.append(TradeEntry(
                date=last_date, action="SELL",
                price=round(sell_price, 2),
                shares=position["shares"],
                value_usd=round(proceeds, 2),
                fee_usd=round(fee, 4),
                pnl=round(pnl, 2),
                balance_after=round(balance, 2),
                reason="バックテスト終了",
            ))
            equity_curve[-1] = (last_date, round(balance, 2))

        return BacktestResult(
            bot_type="TREND",
            start_date=start,
            end_date=end,
            initial_balance=self.initial_balance,
            equity_curve=equity_curve,
            trades=trades,
            bh_curve=bh_curve,
        )

    def _run_short_hourly(self, start: str, end: str) -> BacktestResult:
        """
        SHORT bot を時間足データで検証。
        yfinance interval=1h は最大730日分のみ取得可能。
        """
        import datetime
        start_ext = (pd.Timestamp(start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")

        # yfinance 1h は「システム時刻から730日以内」しか取得不可
        # システム時刻ベースで安全なstart_extを計算する
        sys_now   = pd.Timestamp.utcnow()
        min_start = (sys_now - pd.Timedelta(days=720)).strftime("%Y-%m-%d")
        # start と min_start の遅い方を採用 (文字列ISO比較)
        safe_start = start if start >= min_start else min_start
        start_ext  = (pd.Timestamp(safe_start) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
        if start_ext < min_start:
            start_ext = min_start

        print(f"  [DL] BTC-USD 1h  {start_ext} → latest ...", end=" ", flush=True)
        raw = yf.download("BTC-USD", start=start_ext,
                          interval="1h", auto_adjust=True, progress=False)
        if raw.empty:
            print("データなし。日足にフォールバック")
            return self._run_short(start, end)

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw = raw[["Open","High","Low","Close","Volume"]].dropna(subset=["Close"])
        print(f"{len(raw)}行")

        btc = compute_indicators(raw)

        sys.path.insert(0, str(_ROOT / "short"))
        from analyzer import RuleBasedAnalyzer  # type: ignore
        analyzer = RuleBasedAnalyzer()

        from kelly import KellyCriterion, DrawdownManager
        from entry_optimizer import check_entry_quality
        kelly  = KellyCriterion(fraction=0.25)
        dd_mgr = DrawdownManager(self.initial_balance)

        balance       = self.initial_balance
        position      = None
        trades: list[TradeEntry] = []
        equity_curve  = []
        bh_curve      = []
        bh_start_price= None

        bt_df = btc.loc[start:]
        if bt_df.empty:
            raise ValueError(f"{start} 以降のデータなし")

        print(f"  シミュレーション開始: {len(bt_df)} hourly bars")

        for date, row in bt_df.iterrows():
            price = float(row["Close"])
            if np.isnan(price):
                continue

            # B&H
            if bh_start_price is None:
                bh_start_price = price
            bh_curve.append((str(date), round(self.initial_balance * price / bh_start_price, 2)))

            pos_val = (position["shares"] * price) if position else 0.0
            equity  = balance + pos_val

            # 出口チェック
            if position:
                if price > position["peak"]:
                    position["peak"] = price
                change_pct  = (price - position["price"]) / position["price"]
                trailing_dd = (position["peak"] - price) / position["peak"]
                regime_key  = position.get("regime", "RANGE")

                atr_pct_pos = position.get("atr_pct", None)
                if atr_pct_pos and atr_pct_pos > 0:
                    am = _SHORT_ATR_MULT[regime_key]
                    tp_pct2    = min(max(atr_pct_pos * am["tp_atr"],  0.06), 0.25)
                    sl_pct2    = max(min(-atr_pct_pos * am["sl_atr"], -0.04), -0.12)
                    trail_pct2 = min(max(atr_pct_pos * am["trail_atr"], 0.03), 0.12)
                else:
                    p2 = _SHORT_PARAMS[regime_key]
                    tp_pct2 = p2["tp"]; sl_pct2 = p2["sl"]; trail_pct2 = p2["trail"]

                should_exit = False
                exit_reason = ""
                if change_pct >= tp_pct2:
                    should_exit = True; exit_reason = f"利確+{change_pct*100:.1f}%"
                elif trailing_dd >= trail_pct2:
                    should_exit = True; exit_reason = f"トレーリング-{trailing_dd*100:.1f}%"
                elif change_pct <= sl_pct2:
                    should_exit = True; exit_reason = f"損切り{change_pct*100:.1f}%"

                if should_exit:
                    sell_price = price * (1 - SLIP_RATE)
                    proceeds   = position["shares"] * sell_price
                    fee        = proceeds * FEE_RATE
                    pnl        = proceeds - fee - position["cost"]
                    balance   += proceeds - fee
                    trades.append(TradeEntry(
                        date=str(date), action="SELL",
                        price=round(sell_price, 2), shares=position["shares"],
                        value_usd=round(proceeds, 2), fee_usd=round(fee, 4),
                        pnl=round(pnl, 2), balance_after=round(balance, 2),
                        reason=exit_reason,
                    ))
                    position = None
                    equity   = balance

            # エントリー
            if position is None:
                market_data = make_short_market_data(row)
                analysis    = analyzer.analyze(market_data)
                if analysis["decision"] == "BUY":
                    t = market_data["technicals"]
                    adx_v   = t.get("adx") or 0
                    di_plus = t.get("di_plus") or 0
                    di_minus= t.get("di_minus") or 0
                    if adx_v > 25:
                        regime = "BULL" if di_plus > di_minus else "BEAR"
                    elif t.get("ma50") and price:
                        regime = "BULL" if price > (t.get("ma50") or 0) else "BEAR"
                    else:
                        regime = "RANGE"

                    should_enter, _, _ = check_entry_quality(t, regime)
                    if should_enter:
                        recent_sells = [t2 for t2 in trades if t2.action == "SELL"]
                        wr  = (len([t2 for t2 in recent_sells[-30:] if t2.pnl > 0]) /
                               max(len(recent_sells[-30:]), 1))
                        aw  = (np.mean([t2.pnl for t2 in recent_sells[-30:] if t2.pnl > 0])
                               if any(t2.pnl > 0 for t2 in recent_sells[-30:]) else 150)
                        al  = (abs(np.mean([t2.pnl for t2 in recent_sells[-30:] if t2.pnl < 0]))
                               if any(t2.pnl < 0 for t2 in recent_sells[-30:]) else 100)
                        dd_mult = dd_mgr.exposure_multiplier(equity)
                        invest  = min(kelly.position_size_usd(balance, wr, aw, al) * dd_mult,
                                      balance * 0.95)
                        if invest > 100 and dd_mult > 0:
                            buy_price    = price * (1 + SLIP_RATE)
                            fee          = invest * FEE_RATE
                            shares       = (invest - fee) / buy_price
                            entry_regime = _regime_from_row(row, price)
                            atr_val2     = float(t2.get("atr") or 0)
                            atr_pct2     = (atr_val2 / price) if price > 0 else 0
                            balance     -= invest
                            position     = {"price": buy_price, "shares": shares,
                                            "peak": buy_price, "cost": invest,
                                            "regime": entry_regime, "atr_pct": atr_pct2}
                            trades.append(TradeEntry(
                                date=str(date), action="BUY",
                                price=round(buy_price, 2), shares=round(shares, 8),
                                value_usd=round(invest, 2), fee_usd=round(fee, 4),
                                pnl=0.0, balance_after=round(balance, 2),
                                reason=analysis["reasoning"][:80],
                            ))
                            equity = balance + shares * price

            equity_curve.append((str(date), round(equity, 2)))

        # 未決済クローズ
        if position and not bt_df.empty:
            last_price = float(bt_df.iloc[-1]["Close"])
            sell_price = last_price * (1 - SLIP_RATE)
            proceeds   = position["shares"] * sell_price
            fee        = proceeds * FEE_RATE
            pnl        = proceeds - fee - position["cost"]
            balance   += proceeds - fee
            last_date  = str(bt_df.index[-1])
            trades.append(TradeEntry(
                date=last_date, action="SELL",
                price=round(sell_price, 2), shares=position["shares"],
                value_usd=round(proceeds, 2), fee_usd=round(fee, 4),
                pnl=round(pnl, 2), balance_after=round(balance, 2),
                reason="バックテスト終了",
            ))
            equity_curve[-1] = (last_date, round(balance, 2))

        return BacktestResult(
            bot_type=self.bot_type + "_1h",
            start_date=start,
            end_date=end,
            initial_balance=self.initial_balance,
            equity_curve=equity_curve,
            trades=trades,
            bh_curve=bh_curve,
        )

    def _run_medium(self, start: str, end: str) -> BacktestResult:
        import datetime
        start_ext = (pd.Timestamp(start) - pd.Timedelta(days=250)).strftime("%Y-%m-%d")

        btc = self._download("BTC-USD", start_ext, end)
        eth = self._download("ETH-USD", start_ext, end)
        if btc.empty:
            raise ValueError("BTC-USD データ取得失敗")

        btc = compute_indicators(btc)

        # ETH も計算して BTC/ETH 統計裁定の Z スコアを算出
        eth_close = None
        z_series  = None
        if not eth.empty:
            eth = compute_indicators(eth)
            btc_aligned, eth_aligned = btc["Close"].align(eth["Close"], join="inner")
            z_series = compute_stat_arb(btc_aligned, eth_aligned, window=60)

        macro = self._download_macro(start_ext, end)

        sys.path.insert(0, str(_ROOT / "medium"))
        from analyzer import MediumTermAnalyzer  # type: ignore
        analyzer = MediumTermAnalyzer()

        from kelly import KellyCriterion, DrawdownManager
        kelly  = KellyCriterion(fraction=0.25)
        dd_mgr = DrawdownManager(self.initial_balance)

        balance     = self.initial_balance
        position    = None   # {"price", "shares", "cost", "ladder_hits", "peak"}
        trades: list[TradeEntry] = []
        equity_curve = []
        bh_curve     = []
        bh_start     = None

        bt_df = btc.loc[start:]
        if bt_df.empty:
            raise ValueError(f"{start} 以降のデータなし")

        print(f"  シミュレーション開始: {len(bt_df)} bars")

        for date, row in bt_df.iterrows():
            price = float(row["Close"])
            if np.isnan(price):
                continue

            # B&H
            if bh_start is None:
                bh_start = price
            bh_curve.append((str(date.date()),
                              round(self.initial_balance * price / bh_start, 2)))

            pos_val = (position["shares"] * price) if position else 0.0
            equity  = balance + pos_val

            # 出口チェック（保有中）
            if position:
                if price > position.get("peak", position["price"]):
                    position["peak"] = price

                change_pct = (price - position["price"]) / position["price"]

                # ラダー利確（エントリー時レジームのラダーを使用）
                for target_pct, fraction in position.get("ladder", [(0.05, 0.33), (0.10, 0.33), (0.15, 1.0)]):
                    key = str(target_pct)
                    if key in position.get("ladder_hits", []):
                        continue
                    if change_pct >= target_pct:
                        sell_shares = position["shares"] * fraction
                        sell_price  = price * (1 - SLIP_RATE)
                        proceeds    = sell_shares * sell_price
                        fee         = proceeds * FEE_RATE
                        cost_frac   = position["cost"] * fraction
                        pnl         = proceeds - fee - cost_frac
                        balance    += proceeds - fee
                        position["shares"] -= sell_shares
                        position["cost"]   -= cost_frac
                        if "ladder_hits" not in position:
                            position["ladder_hits"] = []
                        position["ladder_hits"].append(key)
                        trades.append(TradeEntry(
                            date=str(date.date()), action="SELL",
                            price=round(sell_price, 2),
                            shares=round(sell_shares, 8),
                            value_usd=round(proceeds, 2),
                            fee_usd=round(fee, 4),
                            pnl=round(pnl, 2),
                            balance_after=round(balance, 2),
                            reason=f"ラダー+{target_pct*100:.0f}%",
                        ))

                if position["shares"] < 1e-9:
                    position = None
                else:
                    # 損切り / トレーリング（エントリー時レジームの値を使用）
                    trailing_dd = (position["peak"] - price) / position["peak"]
                    sl_pct    = position.get("sl", -0.10)
                    trail_pct = position.get("trail", 0.07)
                    if change_pct <= sl_pct:
                        reason = f"損切り{change_pct*100:.1f}%"
                    elif trailing_dd >= trail_pct:
                        reason = f"トレーリング-{trailing_dd*100:.1f}%"
                    else:
                        reason = None

                    if reason:
                        sell_price = price * (1 - SLIP_RATE)
                        proceeds   = position["shares"] * sell_price
                        fee        = proceeds * FEE_RATE
                        pnl        = proceeds - fee - position["cost"]
                        balance   += proceeds - fee
                        trades.append(TradeEntry(
                            date=str(date.date()), action="SELL",
                            price=round(sell_price, 2),
                            shares=position["shares"],
                            value_usd=round(proceeds, 2),
                            fee_usd=round(fee, 4),
                            pnl=round(pnl, 2),
                            balance_after=round(balance, 2),
                            reason=reason,
                        ))
                        position = None

            # エントリー判断
            if position is None:
                eth_row = eth.loc[date] if (not eth.empty and date in eth.index) else None
                z_val   = float(z_series.loc[date]) if (z_series is not None and date in z_series.index) else None
                vix_val = float(macro["VIX"].loc[date]) if ("VIX" in macro and date in macro["VIX"].index) else None
                tnx_val = float(macro["US10Y"].loc[date]) if ("US10Y" in macro and date in macro["US10Y"].index) else None

                market_data = make_medium_market_data(row, eth_row, z_val, vix_val, tnx_val)
                analysis    = analyzer.analyze(market_data)
                decision    = analysis["decision"]

                if decision == "BUY":
                    entry_regime = _regime_from_row(row, price)

                if decision == "BUY":
                    recent_sells = [t for t in trades if t.action == "SELL"][-30:]
                    wr = len([t for t in recent_sells if t.pnl > 0]) / max(len(recent_sells), 1)
                    aw = np.mean([t.pnl for t in recent_sells if t.pnl > 0]) if any(t.pnl>0 for t in recent_sells) else 200
                    al = abs(np.mean([t.pnl for t in recent_sells if t.pnl < 0])) if any(t.pnl<0 for t in recent_sells) else 100

                    dd_mult = dd_mgr.exposure_multiplier(equity)
                    invest  = kelly.position_size_usd(balance, wr, aw, al) * dd_mult
                    invest  = min(invest, balance * 0.95)

                    if invest > 100 and dd_mult > 0:
                        buy_price    = price * (1 + SLIP_RATE)
                        fee          = invest * FEE_RATE
                        shares       = (invest - fee) / buy_price
                        mp           = _MEDIUM_PARAMS[entry_regime]
                        balance     -= invest
                        position     = {
                            "price":       buy_price,
                            "shares":      shares,
                            "cost":        invest,
                            "peak":        buy_price,
                            "ladder_hits": [],
                            "ladder":      mp["ladder"],
                            "sl":          mp["sl"],
                            "trail":       mp["trail"],
                            "regime":      entry_regime,
                        }
                        trades.append(TradeEntry(
                            date=str(date.date()), action="BUY",
                            price=round(buy_price, 2),
                            shares=round(shares, 8),
                            value_usd=round(invest, 2),
                            fee_usd=round(fee, 4),
                            pnl=0.0,
                            balance_after=round(balance, 2),
                            reason=analysis["reasoning"][:80],
                        ))
                        equity = balance + shares * price

            equity_curve.append((str(date.date()), round(equity, 2)))

        # 最終クローズ
        if position and not bt_df.empty:
            last_price = float(bt_df.iloc[-1]["Close"])
            sell_price = last_price * (1 - SLIP_RATE)
            proceeds   = position["shares"] * sell_price
            fee        = proceeds * FEE_RATE
            pnl        = proceeds - fee - position["cost"]
            balance   += proceeds - fee
            last_date  = str(bt_df.index[-1].date())
            trades.append(TradeEntry(
                date=last_date, action="SELL",
                price=round(sell_price, 2),
                shares=position["shares"],
                value_usd=round(proceeds, 2),
                fee_usd=round(fee, 4),
                pnl=round(pnl, 2),
                balance_after=round(balance, 2),
                reason="バックテスト終了",
            ))
            equity_curve[-1] = (last_date, round(balance, 2))

        return BacktestResult(
            bot_type=self.bot_type,
            start_date=start,
            end_date=end,
            initial_balance=self.initial_balance,
            equity_curve=equity_curve,
            trades=trades,
            bh_curve=bh_curve,
        )

    def _run_volt(self, start: str, end: str) -> BacktestResult:
        """
        VOLT bot: ボラティリティターゲティング + デュアルモメンタム + MA200

        プロのヘッジファンド（AQR/Bridgewater/Man Group）が実際に使う手法：

        1. デュアルモメンタム (Gary Antonacci)
           - 12ヶ月リターン > 0% → 保有候補
           - 12ヶ月リターン < 0% → 即キャッシュ（2022年の-75%を自動回避）

        2. MA200トレンドフィルター
           - 価格 > MA200 → 保有候補（二重の下落防止）

        3. ボラティリティターゲティング
           - ポジション率 = target_vol / realized_vol（年率換算）
           - ボラが高い（暴落前後）→ 自動縮小
           - ボラが低い（安定上昇）→ 自動拡大
           - 週次リバランスで継続調整
        """
        p = _VOLT_PARAMS
        start_ext = (pd.Timestamp(start) - pd.Timedelta(days=300)).strftime("%Y-%m-%d")

        btc = self._download("BTC-USD", start_ext, end)
        if btc.empty:
            raise ValueError("BTC-USD データ取得失敗")
        btc = compute_indicators(btc)

        balance           = self.initial_balance
        shares            = 0.0
        cost_basis        = 0.0   # 保有株のコスト合計（正確なPnL計算用）
        cppi_floor        = self.initial_balance * p["cppi_floor_pct"]  # 固定フロア（動かさない）
        trades: list[TradeEntry] = []
        equity_curve      = []
        bh_curve          = []
        bh_start          = None
        last_rebal_date   = None

        bt_df = btc.loc[start:]
        if bt_df.empty:
            raise ValueError(f"{start} 以降のデータなし")

        print(f"  シミュレーション開始: {len(bt_df)} bars  (VOLT: VolTargeting+DualMomentum+MA200)")
        print(f"  target_vol={p['target_vol']*100:.0f}% / rebal>{p['rebal_threshold']*100:.0f}%drift / "
              f"12mモメンタム+MA200フィルター")

        for date, row in bt_df.iterrows():
            price = float(row["Close"])
            if np.isnan(price):
                continue

            # B&H
            if bh_start is None:
                bh_start = price
            bh_curve.append((str(date.date()),
                              round(self.initial_balance * price / bh_start, 2)))

            equity = balance + shares * price

            # ── 週次リバランス ─────────────────────────────────────
            is_weekly = (last_rebal_date is None or
                         (date - last_rebal_date).days >= p["recheck_days"])

            if is_weekly:
                last_rebal_date = date

                mom_12m      = float(row.get("momentum_12m") or np.nan)
                ma200_val    = float(row.get("ma200") or 0)
                realized_vol = float(row.get("realized_vol") or np.nan)

                positive_momentum = (not np.isnan(mom_12m)) and (mom_12m > 0)
                above_ma200       = (ma200_val > 0) and (price > ma200_val)

                if np.isnan(realized_vol) or realized_vol <= 0.01:
                    vol_scalar = 0.4
                else:
                    vol_scalar = min(p["target_vol"] / realized_vol, p["max_invest_pct"])

                # CPPI: クッション = 資産 - 固定フロア
                # フロアに近づくとポジションを強制縮小（ギャップリスクあるが大幅保護）
                cushion      = max(equity - cppi_floor, 0.0)
                cppi_max_pct = min(cushion * p["cppi_multiplier"] / equity,
                                   p["max_invest_pct"]) if equity > 0 else 0.0

                # VolTargeting と CPPI の小さい方を採用
                vol_target_pct = vol_scalar if (above_ma200 and positive_momentum) else 0.0
                target_pct     = min(vol_target_pct, cppi_max_pct)
                current_pct = (shares * price) / equity if equity > 0 else 0.0
                drift       = target_pct - current_pct

                if abs(drift) > p["rebal_threshold"]:
                    if drift > 0:
                        invest = min(drift * equity, balance * 0.999)
                        if invest > 10:
                            buy_price  = price * (1 + SLIP_RATE)
                            fee        = invest * FEE_RATE
                            new_sh     = (invest - fee) / buy_price
                            balance   -= invest
                            shares    += new_sh
                            cost_basis += invest   # コスト合計に追加
                            vol_str  = f"{realized_vol*100:.0f}%" if not np.isnan(realized_vol) else "N/A"
                            mom_str  = f"{mom_12m*100:.0f}%" if not np.isnan(mom_12m) else "N/A"
                            trades.append(TradeEntry(
                                date=str(date.date()), action="BUY",
                                price=round(buy_price, 2), shares=round(new_sh, 8),
                                value_usd=round(invest, 2), fee_usd=round(fee, 4),
                                pnl=0.0, balance_after=round(balance, 2),
                                reason=f"VolTarget {target_pct*100:.0f}% vol={vol_str} mom={mom_str}",
                            ))
                    else:
                        if shares > 1e-9 and current_pct > 0:
                            sell_ratio      = abs(drift) / current_pct
                            sell_sh         = shares * min(sell_ratio, 1.0)
                            sell_price      = price * (1 - SLIP_RATE)
                            proceeds        = sell_sh * sell_price
                            fee             = proceeds * FEE_RATE
                            # 按分コスト
                            cost_per_share  = cost_basis / shares if shares > 0 else price
                            cost_sold       = sell_sh * cost_per_share
                            pnl             = proceeds - fee - cost_sold
                            balance        += proceeds - fee
                            shares         -= sell_sh
                            cost_basis     -= cost_sold
                            if shares < 1e-9:
                                shares     = 0.0
                                cost_basis = 0.0
                            reason_exit = ("MA200下" if not above_ma200 else
                                           "12m負" if not positive_momentum else
                                           f"rebal→{target_pct*100:.0f}%")
                            vol_str = f"{realized_vol*100:.0f}%" if not np.isnan(realized_vol) else "N/A"
                            trades.append(TradeEntry(
                                date=str(date.date()), action="SELL",
                                price=round(sell_price, 2), shares=round(sell_sh, 8),
                                value_usd=round(proceeds, 2), fee_usd=round(fee, 4),
                                pnl=round(pnl, 2), balance_after=round(balance, 2),
                                reason=f"{reason_exit} vol={vol_str}",
                            ))

                equity = balance + shares * price

            equity_curve.append((str(date.date()), round(equity, 2)))

        # 最終クローズ
        if shares > 1e-9 and not bt_df.empty:
            last_price = float(bt_df.iloc[-1]["Close"])
            sell_price = last_price * (1 - SLIP_RATE)
            proceeds   = shares * sell_price
            fee        = proceeds * FEE_RATE
            pnl        = proceeds - fee - cost_basis
            balance   += proceeds - fee
            last_date  = str(bt_df.index[-1].date())
            trades.append(TradeEntry(
                date=last_date, action="SELL",
                price=round(sell_price, 2), shares=round(shares, 8),
                value_usd=round(proceeds, 2), fee_usd=round(fee, 4),
                pnl=round(pnl, 2), balance_after=round(balance, 2),
                reason="バックテスト終了",
            ))
            equity_curve[-1] = (last_date, round(balance, 2))

        return BacktestResult(
            bot_type="VOLT",
            start_date=start,
            end_date=end,
            initial_balance=self.initial_balance,
            equity_curve=equity_curve,
            trades=trades,
            bh_curve=bh_curve,
        )

    def _run_attack(self, start: str, end: str) -> BacktestResult:
        """
        ATTACK bot: 攻撃型トレンドフォロー

        「負けてもいい、大きく勝つ」設計。
        - 勝率: 40-50%（半分は負ける）
        - 勝ち負けの比率: 勝ちが負けの3倍以上
        - 長期で見ると大きくプラス

        プロの真理: 「損小利大」= 少し頻繁に負けても
                   1回の大勝ちでカバーする
        """
        p = _ATTACK_PARAMS
        start_ext = (pd.Timestamp(start) - pd.Timedelta(days=250)).strftime("%Y-%m-%d")

        btc = self._download("BTC-USD", start_ext, end)
        if btc.empty:
            raise ValueError("BTC-USD データ取得失敗")
        btc = compute_indicators(btc)

        balance            = self.initial_balance
        position           = None
        trades: list[TradeEntry] = []
        equity_curve       = []
        bh_curve           = []
        bh_start           = None
        last_decision_date = None

        bt_df = btc.loc[start:]
        if bt_df.empty:
            raise ValueError(f"{start} 以降のデータなし")

        print(f"  シミュレーション開始: {len(bt_df)} bars  (ATTACK: 攻撃型トレンドフォロー)")
        print(f"  trail-{p['trail_stop']*100:.0f}% / MA200*{p['exit_buffer']} / RSI>={p['rsi_entry_min']} / 投資{p['invest_pct']*100:.0f}%")

        for date, row in bt_df.iterrows():
            price = float(row["Close"])
            if np.isnan(price):
                continue

            if bh_start is None:
                bh_start = price
            bh_curve.append((str(date.date()),
                              round(self.initial_balance * price / bh_start, 2)))

            pos_val = (position["shares"] * price) if position else 0.0
            equity  = balance + pos_val

            # EXIT判断（毎日）
            if position:
                if price > position["peak"]:
                    position["peak"] = price

                change_pct  = (price - position["price"]) / position["price"]
                trailing_dd = (position["peak"] - price) / position["peak"]
                ma200_val   = float(row.get("ma200") or 0)

                ma_exit    = (ma200_val > 0) and (price < ma200_val * p["exit_buffer"])
                trail_exit = trailing_dd >= p["trail_stop"]

                if ma_exit or trail_exit:
                    reason = (f"MA200-5%割れ" if ma_exit
                              else f"トレーリング -{trailing_dd*100:.1f}%")
                    sell_price = price * (1 - SLIP_RATE)
                    proceeds   = position["shares"] * sell_price
                    fee        = proceeds * FEE_RATE
                    pnl        = proceeds - fee - position["cost"]
                    balance   += proceeds - fee
                    trades.append(TradeEntry(
                        date=str(date.date()), action="SELL",
                        price=round(sell_price, 2), shares=position["shares"],
                        value_usd=round(proceeds, 2), fee_usd=round(fee, 4),
                        pnl=round(pnl, 2), balance_after=round(balance, 2),
                        reason=reason,
                    ))
                    position = None
                    equity   = balance

            # エントリー判断（週次）
            is_weekly = (last_decision_date is None or
                         (date - last_decision_date).days >= p["recheck_days"])

            if position is None and is_weekly:
                last_decision_date = date
                ma200_val = float(row.get("ma200") or 0)
                rsi_val   = float(row.get("rsi")   or 0)
                macd_hist = float(row.get("macd_hist") or 0)

                if (ma200_val > 0 and price > ma200_val and
                        rsi_val >= p["rsi_entry_min"] and macd_hist > 0):
                    invest    = balance * p["invest_pct"]
                    buy_price = price * (1 + SLIP_RATE)
                    fee       = invest * FEE_RATE
                    shares    = (invest - fee) / buy_price
                    balance  -= invest
                    position  = {"price": buy_price, "shares": shares,
                                 "cost": invest, "peak": buy_price}
                    trades.append(TradeEntry(
                        date=str(date.date()), action="BUY",
                        price=round(buy_price, 2), shares=round(shares, 8),
                        value_usd=round(invest, 2), fee_usd=round(fee, 4),
                        pnl=0.0, balance_after=round(balance, 2),
                        reason=f"MA200上 RSI={rsi_val:.0f} MACD上",
                    ))
                    equity = balance + shares * price

            equity_curve.append((str(date.date()), round(equity, 2)))

        if position and not bt_df.empty:
            last_price = float(bt_df.iloc[-1]["Close"])
            sell_price = last_price * (1 - SLIP_RATE)
            proceeds   = position["shares"] * sell_price
            fee        = proceeds * FEE_RATE
            pnl        = proceeds - fee - position["cost"]
            balance   += proceeds - fee
            last_date  = str(bt_df.index[-1].date())
            trades.append(TradeEntry(
                date=last_date, action="SELL",
                price=round(sell_price, 2), shares=position["shares"],
                value_usd=round(proceeds, 2), fee_usd=round(fee, 4),
                pnl=round(pnl, 2), balance_after=round(balance, 2),
                reason="バックテスト終了",
            ))
            equity_curve[-1] = (last_date, round(balance, 2))

        return BacktestResult(
            bot_type="ATTACK",
            start_date=start,
            end_date=end,
            initial_balance=self.initial_balance,
            equity_curve=equity_curve,
            trades=trades,
            bh_curve=bh_curve,
        )
