"""
LONG bot 情報収集モジュール — ファンダメンタルズ + マクロ拡張版

追加データ:
  - VIX / DXY / US10Y (yfinance 無料)
  - M2マネーサプライ (FRED 無料CSV)
  - 各銘柄にADX/ボラモメンタム追加
"""

import requests
import feedparser
import pandas as pd
import ta
import yfinance as yf
from datetime import datetime
from typing import Optional

WATCHLIST = {
    "AAPL":  "Apple",
    "MSFT":  "Microsoft",
    "GOOGL": "Alphabet",
    "AMZN":  "Amazon",
    "NVDA":  "NVIDIA",
    "AMD":   "AMD",
    "TSLA":  "Tesla",
    "META":  "Meta",
    "PLTR":  "Palantir",
    "ARM":   "Arm Holdings",
    "AVGO":  "Broadcom",
    "COIN":  "Coinbase",
    "MSTR":  "MicroStrategy",
    "BRK-B": "Berkshire Hathaway",
    "SPY":   "S&P500 ETF",
    "QQQ":   "Nasdaq ETF",
    "VT":    "全世界株ETF",
}

MACRO_POSITIVE = ["rate cut", "stimulus", "growth", "recovery", "gdp up",
                  "earnings beat", "expansion", "dovish"]
MACRO_NEGATIVE = ["rate hike", "recession", "inflation", "gdp down",
                  "layoffs", "crisis", "war", "sanctions", "hawkish"]

MACRO_RSS = [
    "https://feeds.reuters.com/reuters/businessNews",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
]


def get_fundamentals(ticker: str) -> dict:
    try:
        t    = yf.Ticker(ticker)
        info = t.info
        hist = t.history(period="1y")

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if not price and not hist.empty:
            price = float(hist["Close"].iloc[-1])

        week52_high = info.get("fiftyTwoWeekHigh")
        from_high   = ((price - week52_high) / week52_high * 100) if price and week52_high else None

        # ADX / ボラモメンタム
        adx_val = vol_mom = None
        if not hist.empty and len(hist) >= 20:
            try:
                adx_ind = ta.trend.ADXIndicator(
                    hist["High"], hist["Low"], hist["Close"], window=14)
                adx_val = float(adx_ind.adx().iloc[-1])
                if pd.isna(adx_val): adx_val = None
            except Exception:
                pass
            try:
                returns = hist["Close"].pct_change()
                vm = returns.rolling(14).mean() / returns.rolling(14).std()
                vol_mom = float(vm.iloc[-1])
                if pd.isna(vol_mom): vol_mom = None
            except Exception:
                pass

        return {
            "ticker":         ticker,
            "name":           info.get("longName", ticker),
            "price":          round(price, 2) if price else None,
            "pe_ratio":       info.get("trailingPE"),
            "forward_pe":     info.get("forwardPE"),
            "revenue_growth": info.get("revenueGrowth"),
            "profit_margin":  info.get("profitMargins"),
            "debt_to_equity": info.get("debtToEquity"),
            "roe":            info.get("returnOnEquity"),
            "week52_high":    week52_high,
            "from_52w_high":  round(from_high, 1) if from_high else None,
            "market_cap":     info.get("marketCap"),
            "adx":            round(adx_val, 2) if adx_val else None,
            "vol_momentum":   round(vol_mom, 4) if vol_mom else None,
        }
    except Exception as e:
        print(f"[long/collector] {ticker} 取得エラー: {e}")
        return {"ticker": ticker}


def get_macro_indicators() -> dict:
    """VIX, DXY, US10Y (yfinance無料)"""
    tickers = {
        "^VIX":      "VIX",
        "DX-Y.NYB":  "DXY",
        "^TNX":      "US10Y",
    }
    result = {}
    for sym, key in tickers.items():
        try:
            hist = yf.Ticker(sym).history(period="30d")
            if not hist.empty:
                val  = float(hist["Close"].iloc[-1])
                prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else val
                ma20 = float(hist["Close"].rolling(20).mean().iloc[-1])
                result[key] = {
                    "value":      round(val, 3),
                    "prev":       round(prev, 3),
                    "ma20":       round(ma20, 3) if not pd.isna(ma20) else None,
                    "change":     round(val - prev, 3),
                    "change_pct": round((val - prev) / prev * 100, 2) if prev else 0,
                    "trend":      "UP" if val > ma20 else "DOWN" if not pd.isna(ma20) else "UNKNOWN",
                }
        except Exception:
            pass
    return result


def get_m2_trend() -> dict:
    """
    M2マネーサプライトレンド (FRED 無料CSV, APIキー不要)
    ビットコインのサイクルは現在M2が主因（4年サイクル理論は崩壊）
    """
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=M2SL"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return {}
        from io import StringIO
        df = pd.read_csv(StringIO(r.text))
        df.columns = ["date", "m2"]
        df["m2"] = pd.to_numeric(df["m2"], errors="coerce")
        df = df.dropna()
        if len(df) < 13:
            return {}
        latest   = float(df["m2"].iloc[-1])
        prev_3m  = float(df["m2"].iloc[-4])   # 約3ヶ月前
        prev_12m = float(df["m2"].iloc[-13])  # 約12ヶ月前
        yoy_chg  = (latest - prev_12m) / prev_12m * 100
        mom_chg  = (latest - prev_3m)  / prev_3m  * 100
        return {
            "latest_b":   round(latest / 1000, 1),    # 兆ドル
            "yoy_pct":    round(yoy_chg, 2),
            "mom_3m_pct": round(mom_chg, 2),
            "trend":      "EXPANDING" if yoy_chg > 3 else ("CONTRACTING" if yoy_chg < -1 else "FLAT"),
        }
    except Exception as e:
        print(f"[long/collector] M2取得エラー: {e}")
        return {}


def get_macro_news() -> dict:
    score = 0
    headlines = []
    for url in MACRO_RSS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:5]:
                title = e.get("title", "").lower()
                headlines.append(e.get("title", ""))
                for w in MACRO_POSITIVE: score += title.count(w)
                for w in MACRO_NEGATIVE: score -= title.count(w)
        except Exception:
            pass
    return {
        "score":     score,
        "headlines": headlines[:10],
        "label":     "positive" if score > 0 else ("negative" if score < 0 else "neutral"),
    }


def score_fundamentals(f: dict) -> int:
    score = 0
    pe, fpe    = f.get("pe_ratio"), f.get("forward_pe")
    rev_growth = f.get("revenue_growth")
    margin     = f.get("profit_margin")
    dte        = f.get("debt_to_equity")
    roe        = f.get("roe")
    from_high  = f.get("from_52w_high")
    vol_mom    = f.get("vol_momentum")

    if pe:
        if pe < 15:    score += 2
        elif pe < 25:  score += 1
        elif pe > 40:  score -= 1
    if fpe and pe and fpe < pe:  score += 1
    if rev_growth:
        if rev_growth > 0.15:   score += 2
        elif rev_growth > 0.05: score += 1
        elif rev_growth < 0:    score -= 1
    if margin and margin > 0.20: score += 1
    if dte and dte < 50:         score += 1
    if roe and roe > 0.15:       score += 1
    if from_high and from_high < -30: score += 1
    if vol_mom and vol_mom > 1.5:     score += 1  # モメンタム確認
    return score


def collect_all(primary_ticker: str = "AAPL") -> dict:
    fundamentals = {}
    scores       = {}
    for ticker in WATCHLIST:
        f = get_fundamentals(ticker)
        fundamentals[ticker] = f
        scores[ticker]       = score_fundamentals(f)

    macro_news   = get_macro_news()
    macro_indic  = get_macro_indicators()
    m2           = get_m2_trend()
    best_ticker  = max(scores, key=lambda t: scores[t]) if scores else primary_ticker

    # LLMセンチメント（マクロニュース対象）
    llm_sentiment = {}
    macro_articles = []
    for url in MACRO_RSS:
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:5]:
                macro_articles.append({"title": e.get("title",""), "summary": e.get("summary","")})
        except Exception:
            pass
    try:
        from llm_sentiment import analyze_with_claude
        llm_sentiment = analyze_with_claude(macro_articles, context="macro/stock")
    except Exception:
        pass

    return {
        "collected_at":    datetime.utcnow().isoformat(),
        "mode":            "long",
        "primary_ticker":  best_ticker,
        "fundamentals":    fundamentals,
        "scores":          scores,
        "macro_news":      macro_news,
        "macro_indicators": macro_indic,
        "m2":              m2,
        "technicals":      fundamentals.get(best_ticker, {}),
        "llm_sentiment":   llm_sentiment,
    }
