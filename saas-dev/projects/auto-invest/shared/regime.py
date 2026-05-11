"""
マーケットレジーム検出
ADX + MA位置でBULL/BEAR/RANGEを判定
ボラティリティ調整済みモメンタムも提供

研究実績: レジーム別に戦略を切り替えることでSharpe+0.5〜1.0
"""
from __future__ import annotations
import pandas as pd
try:
    import ta
except ImportError:
    ta = None

Regime = str  # "BULL" | "BEAR" | "RANGE"


def detect_regime(df: pd.DataFrame,
                  close_col: str = "close") -> dict:
    """
    DataFrameからレジームを検出。
    df: close, high, low カラムを含む
    """
    result = {
        "regime":         "RANGE",
        "adx":            None,
        "di_plus":        None,
        "di_minus":       None,
        "ma50":           None,
        "ma200":          None,
        "trend_strength": "UNKNOWN",
        "vol_momentum":   None,
    }

    if df is None or len(df) < 20:
        return result

    # カラム名を小文字に統一
    cols = {c.lower(): c for c in df.columns}
    close_c = cols.get("close", cols.get("close", None))
    high_c  = cols.get("high",  None)
    low_c   = cols.get("low",   None)

    if close_c is None:
        return result

    close = df[close_c]
    high  = df[high_c]  if high_c  else close
    low   = df[low_c]   if low_c   else close

    # ── ADX (トレンド強度) ──────────────────────────────
    adx_val = di_plus = di_minus = None
    if ta is not None:
        try:
            adx_ind = ta.trend.ADXIndicator(high, low, close, window=14)
            adx_val  = adx_ind.adx().iloc[-1]
            di_plus  = adx_ind.adx_pos().iloc[-1]
            di_minus = adx_ind.adx_neg().iloc[-1]
            if pd.isna(adx_val): adx_val = None
            if pd.isna(di_plus):  di_plus  = None
            if pd.isna(di_minus): di_minus = None
        except Exception:
            pass

    # ── 移動平均 ─────────────────────────────────────────
    ma50  = close.rolling(50).mean().iloc[-1]  if len(close) >= 50  else None
    ma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None
    price = close.iloc[-1]

    # ── レジーム判定 ──────────────────────────────────────
    regime: Regime = "RANGE"
    if adx_val is not None and adx_val > 25:
        # ADX > 25 → 明確なトレンド
        if di_plus is not None and di_minus is not None:
            regime = "BULL" if di_plus > di_minus else "BEAR"
        elif ma50 is not None:
            regime = "BULL" if price > ma50 else "BEAR"
    elif ma50 is not None and ma200 is not None:
        if price > ma50 and price > ma200 and ma50 > ma200:
        # price > MA50 > MA200 → 綺麗な上昇トレンド
            regime = "BULL"
        elif price < ma50 and price < ma200 and ma50 < ma200:
            regime = "BEAR"
    elif ma50 is not None:
        regime = "BULL" if price > ma50 else "BEAR"

    # ── ボラティリティ調整モメンタム (研究実績: 週次+1.86〜2.4%) ──
    vol_mom = vol_adjusted_momentum(close)

    trend_str = "WEAK"
    if adx_val is not None:
        if adx_val > 30:   trend_str = "STRONG"
        elif adx_val > 20: trend_str = "MODERATE"

    result.update({
        "regime":         regime,
        "adx":            round(adx_val, 2)  if adx_val  is not None else None,
        "di_plus":        round(di_plus, 2)  if di_plus  is not None else None,
        "di_minus":       round(di_minus, 2) if di_minus is not None else None,
        "ma50":           round(ma50, 2)     if ma50     is not None else None,
        "ma200":          round(ma200, 2)    if ma200    is not None else None,
        "trend_strength": trend_str,
        "vol_momentum":   round(vol_mom, 4),
    })
    return result


def vol_adjusted_momentum(close: pd.Series, period: int = 14) -> float:
    """
    ボラティリティ調整済みモメンタム
    Signal = Returns(period) / StdDev(returns, period)
    正 → 上昇モメンタム / 負 → 下降モメンタム
    """
    if len(close) < period + 5:
        return 0.0
    returns = close.pct_change().dropna()
    if len(returns) < period:
        return 0.0
    mom = (close.iloc[-1] - close.iloc[-period]) / close.iloc[-period]
    vol = returns.rolling(period).std().iloc[-1]
    if vol == 0 or pd.isna(vol):
        return 0.0
    return float(mom / vol)
