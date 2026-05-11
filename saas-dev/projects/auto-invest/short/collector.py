"""
SHORT bot 情報収集モジュール
APIキー不要・完全無料

追加データ（従来+）:
  - ATR / MA20 / MA50 / ADX / DI+/DI-
  - ボラティリティ調整モメンタム
  - ファンディングレート (Binance先物・無料)
  - オープンインタレスト (Binance先物・無料)
  - ロング/ショート比率 (Binance先物・無料)
"""

import requests
import feedparser
import pandas as pd
import ta
from datetime import datetime
from typing import Optional


POSITIVE_WORDS = [
    "bullish", "surge", "rally", "adoption", "breakout", "record",
    "growth", "gains", "high", "buy", "support", "recovery", "upgrade",
    "partnership", "launch", "approval", "etf", "institutional"
]
NEGATIVE_WORDS = [
    "bearish", "crash", "ban", "hack", "regulation", "lawsuit",
    "sell", "drop", "fall", "decline", "risk", "warning", "fraud",
    "scam", "exploit", "vulnerability", "liquidation", "fear"
]

RSS_FEEDS = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
]

BINANCE_FUTURES = "https://fapi.binance.com"


class MarketDataCollector:

    COINGECKO_BASE = "https://api.coingecko.com/api/v3"

    def get_price(self, coin_id: str = "bitcoin") -> Optional[dict]:
        try:
            url = f"{self.COINGECKO_BASE}/simple/price"
            params = {
                "ids": coin_id,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
            }
            res = requests.get(url, params=params, timeout=10)
            res.raise_for_status()
            return res.json().get(coin_id)
        except Exception as e:
            print(f"[collector] 価格取得エラー: {e}")
            return None

    def get_ohlcv(self, coin_id: str = "bitcoin", days: int = 90) -> Optional[pd.DataFrame]:
        """90日分のOHLCデータ取得 + 拡張テクニカル計算"""
        try:
            url = f"{self.COINGECKO_BASE}/coins/{coin_id}/ohlc"
            params = {"vs_currency": "usd", "days": days}
            res = requests.get(url, params=params, timeout=15)
            res.raise_for_status()
            data = res.json()

            df = pd.DataFrame(data, columns=["timestamp", "open", "high", "low", "close"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.set_index("timestamp")

            # ── 基本テクニカル ─────────────────────────────
            df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
            macd = ta.trend.MACD(df["close"])
            df["macd"]        = macd.macd()
            df["macd_signal"] = macd.macd_signal()
            df["macd_hist"]   = macd.macd_diff()
            bb = ta.volatility.BollingerBands(df["close"])
            df["bb_upper"] = bb.bollinger_hband()
            df["bb_lower"] = bb.bollinger_lband()
            df["bb_mid"]   = bb.bollinger_mavg()

            # ── 拡張テクニカル ─────────────────────────────
            # ATR (ボラティリティ基準のストップ設定に使用)
            df["atr"] = ta.volatility.AverageTrueRange(
                df["high"], df["low"], df["close"], window=14
            ).average_true_range()

            # 移動平均 (マルチタイムフレームフィルター用)
            df["ma20"] = df["close"].rolling(20).mean()
            df["ma50"] = df["close"].rolling(50).mean()

            # ADX + DI+/DI- (トレンド強度判定)
            adx_ind = ta.trend.ADXIndicator(df["high"], df["low"], df["close"], window=14)
            df["adx"]      = adx_ind.adx()
            df["di_plus"]  = adx_ind.adx_pos()
            df["di_minus"] = adx_ind.adx_neg()

            # ボラティリティ調整モメンタム
            # Signal = 14足モメンタム / 14足σ  (論文実績: 週次+1.86〜2.4%)
            returns = df["close"].pct_change()
            df["vol_momentum"] = (
                returns.rolling(14).mean() / returns.rolling(14).std()
            )

            return df
        except Exception as e:
            print(f"[collector] OHLCVデータ取得エラー: {e}")
            return None

    def get_fear_greed(self) -> Optional[dict]:
        try:
            res = requests.get("https://api.alternative.me/fng/", timeout=10)
            res.raise_for_status()
            data = res.json()["data"][0]
            return {
                "value": int(data["value"]),
                "label": data["value_classification"],
            }
        except Exception as e:
            print(f"[collector] Fear&Greed取得エラー: {e}")
            return None


class DerivativesCollector:
    """Binance先物データ（無料・APIキー不要）"""

    def get_funding_rate(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """最新のファンディングレート（8時間ごと）"""
        try:
            r = requests.get(
                f"{BINANCE_FUTURES}/fapi/v1/fundingRate",
                params={"symbol": symbol, "limit": 3},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    return float(data[-1]["fundingRate"])
        except Exception:
            pass
        return None

    def get_open_interest(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """オープンインタレスト（BTC建て）"""
        try:
            r = requests.get(
                f"{BINANCE_FUTURES}/fapi/v1/openInterest",
                params={"symbol": symbol},
                timeout=10
            )
            if r.status_code == 200:
                return float(r.json().get("openInterest", 0))
        except Exception:
            pass
        return None

    def get_long_short_ratio(self, symbol: str = "BTCUSDT") -> Optional[float]:
        """グローバルロング/ショート比率"""
        try:
            r = requests.get(
                f"{BINANCE_FUTURES}/futures/data/globalLongShortAccountRatio",
                params={"symbol": symbol, "period": "1h", "limit": 2},
                timeout=10
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    return float(data[-1]["longShortRatio"])
        except Exception:
            pass
        return None

    def collect(self, symbol: str = "BTCUSDT") -> dict:
        result = {}
        fr = self.get_funding_rate(symbol)
        oi = self.get_open_interest(symbol)
        ls = self.get_long_short_ratio(symbol)
        if fr is not None: result["funding_rate"] = fr
        if oi is not None: result["open_interest"] = oi
        if ls is not None: result["long_short_ratio"] = ls
        return result


class NewsCollector:

    def get_news(self, max_items: int = 10) -> list[dict]:
        articles = []
        for feed_url in RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:max_items // len(RSS_FEEDS) + 1]:
                    articles.append({
                        "title":     entry.get("title", ""),
                        "summary":   entry.get("summary", ""),
                        "published": entry.get("published", ""),
                        "source":    feed.feed.get("title", feed_url),
                    })
            except Exception as e:
                print(f"[collector] RSS取得エラー ({feed_url}): {e}")
        return articles[:max_items]

    def calc_sentiment(self, articles: list[dict]) -> dict:
        score = 0
        for article in articles:
            text = (article.get("title", "") + " " + article.get("summary", "")).lower()
            for word in POSITIVE_WORDS: score += text.count(word)
            for word in NEGATIVE_WORDS: score -= text.count(word)
        return {
            "score": score,
            "count": len(articles),
            "label": "positive" if score > 0 else ("negative" if score < 0 else "neutral"),
        }


def collect_all(coin_id: str = "bitcoin") -> dict:
    market = MarketDataCollector()
    deriv  = DerivativesCollector()
    news_c = NewsCollector()

    price      = market.get_price(coin_id)
    ohlcv      = market.get_ohlcv(coin_id, days=90)
    fear_greed = market.get_fear_greed()
    articles   = news_c.get_news()
    sentiment  = news_c.calc_sentiment(articles)

    # デリバティブデータ (BTC専用)
    derivatives = {}
    if coin_id == "bitcoin":
        print("    デリバティブデータ取得中...")
        derivatives = deriv.collect("BTCUSDT")

    technicals = {}
    if ohlcv is not None and not ohlcv.empty:
        latest = ohlcv.iloc[-1]
        def safe(v): return round(float(v), 6) if pd.notna(v) else None

        technicals = {
            # 基本
            "current_price": safe(latest["close"]),
            "rsi":           safe(latest["rsi"]),
            "macd":          safe(latest["macd"]),
            "macd_signal":   safe(latest["macd_signal"]),
            "macd_hist":     safe(latest["macd_hist"]),
            "bb_upper":      safe(latest["bb_upper"]),
            "bb_lower":      safe(latest["bb_lower"]),
            "bb_mid":        safe(latest["bb_mid"]),
            # 拡張
            "atr":           safe(latest["atr"]),
            "ma20":          safe(latest["ma20"]),
            "ma50":          safe(latest["ma50"]),
            "adx":           safe(latest["adx"]),
            "di_plus":       safe(latest["di_plus"]),
            "di_minus":      safe(latest["di_minus"]),
            "vol_momentum":  safe(latest["vol_momentum"]),
            # 前足との比較
            "macd_hist_prev": safe(ohlcv.iloc[-2]["macd_hist"]) if len(ohlcv) > 1 else None,
        }

    # LLMセンチメント（Claude API / フォールバック: キーワード）
    llm_sentiment = {}
    try:
        import sys as _sys
        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "shared"))
        from llm_sentiment import analyze_with_claude
        llm_sentiment = analyze_with_claude(articles, context="crypto")
        print(f"    LLM感情: {llm_sentiment.get('label','?')} "
              f"(score={llm_sentiment.get('score',0):+.1f}, "
              f"method={llm_sentiment.get('method','?')})")
    except Exception:
        pass

    return {
        "collected_at":   datetime.utcnow().isoformat(),
        "coin":           coin_id,
        "price":          price,
        "technicals":     technicals,
        "fear_greed":     fear_greed,
        "news_sentiment": sentiment,
        "articles":       articles,
        "derivatives":    derivatives,
        "llm_sentiment":  llm_sentiment,
    }
