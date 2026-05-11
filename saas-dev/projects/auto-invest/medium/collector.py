"""
MEDIUM bot 情報収集モジュール — 拡張版

追加データ:
  - ATR / ADX / ボラモメンタム (各銘柄)
  - BTC-ETH統計的裁定 Zスコア (研究実績: Sharpe 1.58〜2.45)
  - マクロ指標: VIX / DXY / US10Y (yfinance 無料)
"""

import requests
import feedparser
import pandas as pd
import ta
import yfinance as yf
from datetime import datetime
from typing import Optional

POSITIVE_WORDS = ["bullish","surge","rally","growth","gains","recovery","upgrade","adoption"]
NEGATIVE_WORDS = ["bearish","crash","ban","decline","risk","warning","recession","inflation"]

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
]

ASSETS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "Solana",
    "SPY":     "S&P500 ETF",
    "QQQ":     "Nasdaq ETF",
    "NVDA":    "NVIDIA",
    "AMD":     "AMD",
    "TSLA":    "Tesla",
    "META":    "Meta",
    "PLTR":    "Palantir",
    "COIN":    "Coinbase",
    "MSTR":    "MicroStrategy",
    "ARM":     "Arm Holdings",
    "AVGO":    "Broadcom",
}

MACRO_TICKERS = {
    "^VIX":    "VIX恐怖指数",
    "DX-Y.NYB": "ドル指数DXY",
    "^TNX":    "米10年債利回り",
}


def get_daily_data(ticker: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """日足データ取得 + 拡張テクニカル計算"""
    try:
        df = yf.Ticker(ticker).history(period=period)
        if df.empty:
            return None

        # 基本テクニカル
        df["ma50"]  = df["Close"].rolling(50).mean()
        df["ma200"] = df["Close"].rolling(200).mean()
        df["rsi"]   = ta.momentum.RSIIndicator(df["Close"], window=14).rsi()
        macd = ta.trend.MACD(df["Close"])
        df["macd"]        = macd.macd()
        df["macd_signal"] = macd.macd_signal()

        # 拡張: ATR
        df["atr"] = ta.volatility.AverageTrueRange(
            df["High"], df["Low"], df["Close"], window=14
        ).average_true_range()

        # 拡張: ADX
        adx_ind = ta.trend.ADXIndicator(df["High"], df["Low"], df["Close"], window=14)
        df["adx"]      = adx_ind.adx()
        df["di_plus"]  = adx_ind.adx_pos()
        df["di_minus"] = adx_ind.adx_neg()

        # 拡張: ボラ調整モメンタム
        returns = df["Close"].pct_change()
        df["vol_momentum"] = returns.rolling(14).mean() / returns.rolling(14).std()

        return df
    except Exception as e:
        print(f"[medium/collector] {ticker} 取得エラー: {e}")
        return None


def get_asset_signals(ticker: str) -> dict:
    df = get_daily_data(ticker)
    if df is None or len(df) < 5:
        return {}
    latest = df.iloc[-1]
    prev   = df.iloc[-2]
    price  = latest["Close"]
    ma50   = latest["ma50"]
    ma200  = latest["ma200"]

    golden_cross = (prev["ma50"] < prev["ma200"]) and (ma50 > ma200) if pd.notna(ma200) else None
    death_cross  = (prev["ma50"] > prev["ma200"]) and (ma50 < ma200) if pd.notna(ma200) else None

    def safe(v): return round(float(v), 4) if pd.notna(v) else None

    return {
        "ticker":        ticker,
        "price":         round(price, 2),
        "ma50":          safe(ma50),
        "ma200":         safe(ma200),
        "rsi":           safe(latest["rsi"]),
        "macd":          safe(latest["macd"]),
        "macd_signal":   safe(latest["macd_signal"]),
        "atr":           safe(latest["atr"]),
        "adx":           safe(latest["adx"]),
        "di_plus":       safe(latest["di_plus"]),
        "di_minus":      safe(latest["di_minus"]),
        "vol_momentum":  safe(latest["vol_momentum"]),
        "above_ma50":    bool(price > ma50)  if pd.notna(ma50)  else None,
        "above_ma200":   bool(price > ma200) if pd.notna(ma200) else None,
        "golden_cross":  golden_cross,
        "death_cross":   death_cross,
    }


def get_statistical_arb() -> dict:
    """
    BTC-ETH 統計的裁定シグナル
    研究実績: Sharpe 1.58〜2.45 (2024年データ)

    BTC/ETH比率のZスコアを計算:
      Z > +2: BTCが相対割高 → BTCに不利
      Z < -2: BTCが相対割安 → BTCに有利
    """
    try:
        btc = yf.Ticker("BTC-USD").history(period="90d")["Close"]
        eth = yf.Ticker("ETH-USD").history(period="90d")["Close"]
        if btc.empty or eth.empty or len(btc) < 30:
            return {}

        # 同じインデックスに揃える
        ratio = (btc / eth).dropna()
        if len(ratio) < 20:
            return {}

        mean  = ratio.rolling(60).mean().iloc[-1]
        std   = ratio.rolling(60).std().iloc[-1]
        current = ratio.iloc[-1]

        if std == 0 or pd.isna(std) or pd.isna(mean):
            return {}

        z_score = (current - mean) / std

        return {
            "btc_eth_ratio":   round(current, 4),
            "ratio_mean_60d":  round(mean, 4),
            "ratio_std_60d":   round(std, 4),
            "z_score":         round(z_score, 3),
            # 解釈
            "signal": (
                "BTC_CHEAP"      if z_score < -2 else
                "BTC_EXPENSIVE"  if z_score > +2 else
                "NEUTRAL"
            ),
        }
    except Exception as e:
        print(f"[medium/collector] 統計的裁定エラー: {e}")
        return {}


def get_macro_indicators() -> dict:
    """
    マクロ指標 (yfinance 無料)
    VIX, DXY, US10Y
    """
    result = {}
    for ticker, label in MACRO_TICKERS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if not hist.empty:
                val  = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else val
                result[ticker.replace("^","").replace("-","_").replace(".","_")] = {
                    "label":    label,
                    "value":    round(val, 3),
                    "prev":     round(prev, 3),
                    "change":   round(val - prev, 3),
                    "change_pct": round((val - prev) / prev * 100, 2) if prev else 0,
                }
        except Exception:
            pass
    return result


def get_news_sentiment() -> dict:
    articles, score = [], 0
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:5]:
                text = (e.get("title","") + " " + e.get("summary","")).lower()
                for w in POSITIVE_WORDS: score += text.count(w)
                for w in NEGATIVE_WORDS: score -= text.count(w)
                articles.append(e.get("title",""))
        except Exception:
            pass
    return {"score": score, "count": len(articles),
            "label": "positive" if score > 0 else ("negative" if score < 0 else "neutral")}


def collect_all(primary_ticker: str = None) -> dict:
    print("    銘柄データ収集中...")
    signals = {}
    for ticker in ASSETS:
        s = get_asset_signals(ticker)
        if s:
            signals[ticker] = s

    # primary_ticker未指定時: モメンタム最強の銘柄を自動選定
    if primary_ticker is None:
        best_t   = "BTC-USD"
        best_mom = -float("inf")
        for t, s in signals.items():
            mom = s.get("vol_momentum") or 0
            above_ma = s.get("above_ma200")
            if above_ma and mom > best_mom:
                best_mom = mom
                best_t   = t
        primary_ticker = best_t
        print(f"    → primary_ticker 自動選定: {primary_ticker} (VolMom={best_mom:.2f})")

    print("    統計的裁定(BTC-ETH)計算中...")
    stat_arb = get_statistical_arb()

    print("    マクロ指標取得中...")
    macro = get_macro_indicators()

    news = get_news_sentiment()

    # LLMセンチメント
    articles_for_llm = []
    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:5]:
                articles_for_llm.append({"title": e.get("title",""), "summary": e.get("summary","")})
        except Exception:
            pass

    llm_sentiment = {}
    try:
        import sys as _sys
        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "shared"))
        from llm_sentiment import analyze_with_claude
        llm_sentiment = analyze_with_claude(articles_for_llm, context="stock/crypto")
    except Exception:
        pass

    return {
        "collected_at":   datetime.utcnow().isoformat(),
        "mode":           "medium",
        "primary_ticker": primary_ticker,
        "assets":         signals,
        "technicals":     signals.get(primary_ticker, {}),
        "news_sentiment": news,
        "fear_greed":     _get_fear_greed(),
        "stat_arb":       stat_arb,
        "macro":          macro,
        "llm_sentiment":  llm_sentiment,
    }


def _get_fear_greed() -> Optional[dict]:
    try:
        res = requests.get("https://api.alternative.me/fng/", timeout=10)
        d = res.json()["data"][0]
        return {"value": int(d["value"]), "label": d["value_classification"]}
    except Exception:
        return None
