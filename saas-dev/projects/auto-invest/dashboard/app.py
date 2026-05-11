"""
投資ダッシュボード
短期・中期・長期ボットの損益・ポジション・シグナルをリアルタイム表示
起動: python dashboard/app.py
ブラウザ: http://localhost:5000
"""
import sqlite3
import os
import json
import sys
import time
import requests
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string, request
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))

# .env ファイルからAPIキーを読み込む
def _load_dotenv():
    env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
    if not env_path.exists():
        # ai-holdingsルートを探す
        p = Path(__file__).resolve()
        for _ in range(8):
            candidate = p / ".env"
            if candidate.exists():
                env_path = candidate
                break
            p = p.parent
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())

_load_dotenv()

DB_PATH  = Path(__file__).parent.parent / "data" / "trades.db"
DATA_DIR = Path(__file__).parent.parent / "data"

# GitHub Contents API（CDNキャッシュを回避）
GITHUB_REPO    = "ryuu321/ai-holdings"
GITHUB_API_BASE = "https://api.github.com/repos/ryuu321/ai-holdings/contents/saas-dev/projects/auto-invest/data"

# GitHub データキャッシュ
_github_cache: dict = {}
GITHUB_CACHE_TTL = 15


def fetch_github_json(filename: str, force_refresh: bool = False) -> dict | list | None:
    """GitHub Contents APIからJSONを取得（CDNキャッシュ回避・認証対応）"""
    import base64
    global _github_cache
    now = time.time()

    if not force_refresh and filename in _github_cache:
        data, ts = _github_cache[filename]
        if now - ts < GITHUB_CACHE_TTL:
            return data
    try:
        url = f"{GITHUB_API_BASE}/{filename}"
        headers = {"Accept": "application/vnd.github.v3+json"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"token {token}"

        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            content = base64.b64decode(r.json()["content"]).decode("utf-8")
            data = json.loads(content)
            _github_cache[filename] = (data, now)
            return data
        else:
            print(f"  [GITHUB FAIL] {filename} ({r.status_code})")
    except Exception as e:
        print(f"  [GITHUB ERROR] {filename}: {e}")
    # フォールバック：ローカルファイル
    local = DATA_DIR / filename
    if local.exists():
        print(f"  [LOCAL FALLBACK] Using local {filename}")
        try:
            return json.loads(local.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  [LOCAL ERROR] {filename}: {e}")
    return None


app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False  # 日本語をそのまま返す

# ── ライブ価格キャッシュ（過多リクエスト防止） ───────────────
_price_cache: dict = {}   # {ticker: (price, timestamp)}
CACHE_TTL = 30            # 秒


def fetch_live_price(ticker: str) -> float | None:
    """yfinance (株) / CoinGecko (BTC,ETH) でリアルタイム価格取得"""
    now = time.time()
    if ticker in _price_cache:
        price, ts = _price_cache[ticker]
        if now - ts < CACHE_TTL:
            return price

    price = None
    try:
        # 暗号資産は CoinGecko
        crypto_map = {"bitcoin": "bitcoin", "BTC-USD": "bitcoin", "ETH-USD": "ethereum"}
        if ticker in crypto_map:
            r = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": crypto_map[ticker], "vs_currencies": "usd"},
                timeout=5,
            )
            data = r.json()
            price = data.get(crypto_map[ticker], {}).get("usd")
        else:
            # 株は yfinance
            info = yf.Ticker(ticker).fast_info
            price = float(info.last_price) if info.last_price else None
    except Exception:
        pass

    if price is not None:
        _price_cache[ticker] = (price, now)
    return price


def fetch_live_prices(tickers: list[str]) -> dict[str, float]:
    """複数銘柄を一括取得"""
    result = {}
    # 株をまとめて取得（効率化）
    stock_tickers = [t for t in tickers if t not in ("bitcoin", "BTC-USD", "ETH-USD")]
    crypto_tickers = [t for t in tickers if t in ("bitcoin", "BTC-USD", "ETH-USD")]

    if stock_tickers:
        try:
            now = time.time()
            uncached = [t for t in stock_tickers
                        if t not in _price_cache or now - _price_cache[t][1] >= CACHE_TTL]
            if uncached:
                data = yf.download(uncached, period="1d", progress=False, auto_adjust=True)
                if not data.empty:
                    close = data["Close"] if "Close" in data else data
                    for t in uncached:
                        try:
                            p = float(close[t].dropna().iloc[-1]) if t in close.columns else None
                            if p:
                                _price_cache[t] = (p, now)
                        except Exception:
                            pass
            for t in stock_tickers:
                if t in _price_cache:
                    result[t] = _price_cache[t][0]
        except Exception:
            pass

    for t in crypto_tickers:
        p = fetch_live_price(t)
        if p:
            result[t] = p

    return result


_hist_cache = {}  # (ticker, interval) -> (data, timestamp)

def fetch_history(ticker: str, days: int = 30, interval: str = "1d") -> list[dict]:
    """過去N日の価格履歴を返す（キャッシュ対応）"""
    now = time.time()
    cache_key = (ticker, interval)
    if cache_key in _hist_cache:
        data, ts = _hist_cache[cache_key]
        ttl = 300 if interval != "1d" else 3600
        if now - ts < ttl:
            return data

    INTERVAL_PERIOD = {
        "30s": "1d",   # yfinance最小は1m。30s指定時も1mデータを使用
        "1m":  "1d",
        "5m":  "5d",
        "15m": "10d",
        "30m": "30d",
        "1h":  "60d",
        "1d":  f"{days}d",
    }
    # 30sはyfinanceが非対応のため1mで代替
    fetch_interval = "1m" if interval == "30s" else interval
    period = INTERVAL_PERIOD.get(interval, f"{days}d")
    try:
        crypto_map = {"bitcoin": "BTC-USD", "BTC-USD": "BTC-USD", "ETH-USD": "ETH-USD"}
        yf_ticker = crypto_map.get(ticker, ticker)
        df = yf.download(yf_ticker, period=period, interval=fetch_interval,
                         progress=False, auto_adjust=True)
        if df.empty:
            return []
        # MultiIndex対応
        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"][yf_ticker]
        else:
            close = df["Close"] if "Close" in df.columns else df
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]

        from datetime import timedelta
        JST = timezone(timedelta(hours=9))

        def fmt_idx(idx):
            if interval == "1d":
                return str(idx.date()) if not hasattr(idx, 'tzinfo') or idx.tzinfo is None else str(idx.astimezone(JST).date())
            # intraday: UTC→JST変換してから文字列化
            if hasattr(idx, 'tzinfo') and idx.tzinfo is not None:
                return idx.astimezone(JST).strftime("%Y-%m-%d %H:%M")
            return idx.strftime("%Y-%m-%d %H:%M")

        data = [
            {"date": fmt_idx(idx), "price": round(float(v), 4)}
            for idx, v in close.dropna().items()
        ]
        _hist_cache[cache_key] = (data, now)
        return data
    except Exception as e:
        print(f"[CACHE ERR] {e}")
        return []


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────
# API エンドポイント
# ─────────────────────────────────────────────

def _extract_prices_from_snapshot(raw_data: dict) -> dict:
    """raw_data から銘柄→価格のマッピングを取り出す（short/medium/long 両対応）"""
    prices = {}
    # medium/long: raw_data.assets.{TICKER}.price
    for ticker, info in raw_data.get("assets", {}).items():
        if info and info.get("price"):
            prices[ticker] = info["price"]
    # long: raw_data.fundamentals.{TICKER}.price
    for ticker, info in raw_data.get("fundamentals", {}).items():
        if info and info.get("price") and ticker not in prices:
            prices[ticker] = info["price"]
    # short: raw_data.technicals.current_price
    if not prices:
        p = raw_data.get("technicals", {}).get("current_price")
        coin = raw_data.get("coin", "BTC")
        if p:
            prices[coin] = p
    return prices


@app.route("/api/stats")
def api_stats():
    if not DB_PATH.exists():
        return jsonify({"error": "DB not found — run a bot first"})
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM trades WHERE action='BUY'")
    total_buys = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM trades WHERE action='SELL'")
    total_sells = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE action='SELL'")
    realized_pnl = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM trades WHERE action='SELL' AND pnl > 0")
    wins = cur.fetchone()[0]
    win_rate = round(wins / total_sells * 100, 1) if total_sells > 0 else 0.0

    # 最新スナップショットから価格取得（raw_data を使う）
    cur.execute("SELECT raw_data FROM market_snapshots ORDER BY timestamp DESC LIMIT 5")
    prices = {}
    for row in cur.fetchall():
        try:
            rd = json.loads(row["raw_data"] or "{}")
            for k, v in _extract_prices_from_snapshot(rd).items():
                if k not in prices:
                    prices[k] = v
        except Exception:
            pass

    conn.close()
    return jsonify({
        "total_buys":    total_buys,
        "total_sells":   total_sells,
        "realized_pnl":  round(realized_pnl, 2),
        "win_rate":      win_rate,
        "latest_prices": prices,
    })


@app.route("/api/summary_local")
def api_summary_local():
    """優先的にGitHub（トークン使用）から取得し、失敗したらローカルを返す"""
    force = "refresh" in request.args
    data = fetch_github_json("summary.json", force_refresh=force)
    if data:
        return jsonify(data)
    
    path = DATA_DIR / "summary.json"
    if path.exists():
        return path.read_text(encoding="utf-8"), 200, {"Content-Type": "application/json"}
    return jsonify({"portfolios": {}, "recent_trades": [], "stats": {}, "updated_at": ""})


@app.route("/api/live_prices")
def api_live_prices():
    """保有銘柄のリアルタイム価格"""
    tickers = []
    for fname in ["portfolio_long.json", "portfolio_medium.json", "portfolio_short.json", "portfolio_macro.json"]:
        data = fetch_github_json(fname)
        if data:
            tickers += list(data.get("positions", {}).keys())
    # ATTACK: position = {ticker, ...}（単一オブジェクト）
    attack = fetch_github_json("portfolio_attack.json")
    if attack and isinstance(attack.get("position"), dict):
        t = attack["position"].get("ticker")
        if t:
            tickers.append(t)
    # VOLT: ticker フィールドが直接ある
    volt = fetch_github_json("portfolio_volt.json")
    if volt and volt.get("shares", 0) > 1e-9:
        t = volt.get("ticker")
        if t:
            tickers.append(t)
    tickers = list(set(tickers))
    prices = fetch_live_prices(tickers)
    return jsonify({"prices": prices, "updated_at": datetime.now(timezone.utc).isoformat()})


@app.route("/api/history/<ticker>")
def api_history(ticker: str):
    """価格チャート + BUY/SELLマーカー（interval: 5m/30m/1h/1d）"""
    from flask import request as freq
    interval = freq.args.get("interval", "1h")
    if interval not in ("30s", "1m", "5m", "15m", "30m", "1h", "1d"):
        interval = "1h"
    candles = fetch_history(ticker, days=60, interval=interval)
    candle_dates = [c["date"] for c in candles]

    def snap_to_nearest(date_str: str) -> str:
        """UTCタイムスタンプをチャートラベル(YYYY-MM-DD HH:MM, JST)に丸める
        DBは "2026-04-14T13:23:02.67+00:00" 形式（UTC）。
        yfinanceラベルは "2026-04-15 07:00" 形式（JST変換済み）。
        UTC→JSTに変換してから比較する。
        """
        from datetime import datetime, timezone, timedelta
        JST = timezone(timedelta(hours=9))
        if not date_str:
            return candle_dates[-1] if candle_dates else ""
        try:
            # ISO形式をパースしてJSTに変換
            ts_clean = date_str.replace("Z", "+00:00")
            if "+" not in ts_clean[10:] and ts_clean[-1] != "Z":
                ts_clean += "+00:00"   # タイムゾーンなしはUTCとみなす
            dt = datetime.fromisoformat(ts_clean).astimezone(JST)
            normalized = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            # パース失敗時はT→スペース変換のみ
            normalized = date_str.replace("T", " ")
            for sep in ("+", "."):
                pos = normalized.find(sep, 11)
                if pos > 0:
                    normalized = normalized[:pos]
            normalized = normalized[:16].strip()
        if ":" not in date_str:
            normalized = date_str[:10]
        if normalized in candle_dates:
            return normalized
        for c in reversed(candle_dates):
            if c <= normalized:
                return c
        return candle_dates[0] if candle_dates else normalized

    bot_type = freq.args.get("bot_type")
    trades = []
    if DB_PATH.exists():
        conn = get_db()
        cur = conn.cursor()
        query = """SELECT action, price, timestamp, bot_type,
                          COALESCE(amount, 0) as amount,
                          COALESCE(value_usd, 0) as value_usd,
                          COALESCE(pnl, 0) as pnl,
                          COALESCE(risk_level, '') as risk_level
                   FROM trades WHERE coin = ? AND action IN ('BUY','SELL')"""
        params = [ticker]
        if bot_type:
            query += " AND (bot_type = ? OR (bot_type IS NULL AND ? = 'SHORT'))"
            params += [bot_type, bot_type]
        query += " ORDER BY timestamp"

        cur.execute(query, params)
        for r in cur.fetchall():
            snapped = snap_to_nearest(r["timestamp"])
            trades.append({
                "action":       r["action"],
                "price":        round(r["price"], 4),
                "timestamp":    snapped,
                "original_date": r["timestamp"],
                "amount":       round(r["amount"] or 0, 6),
                "value_usd":    round(r["value_usd"] or 0, 2),
                "pnl":          round(r["pnl"] or 0, 2),
                "bot_type":     r["bot_type"] or "SHORT",
                "is_manual":    r["risk_level"] == "MANUAL",
                "is_short":     bool(r["is_short"]) if "is_short" in r.keys() else False,
            })
        conn.close()

    # DBにトレードがない場合、GitHubのportfolioファイルからポジションを補完
    if not trades and bot_type:
        fname_map = {"SHORT": "portfolio_short.json", "MEDIUM": "portfolio_medium.json",
                     "LONG": "portfolio_long.json", "MACRO": "portfolio_macro.json"}
        fname = fname_map.get(bot_type)
        if fname:
            pf = fetch_github_json(fname)
            if pf:
                pos = pf.get("positions", {}).get(ticker)
                if pos and pos.get("bought_at") and pos.get("buy_price"):
                    snapped = snap_to_nearest(pos["bought_at"])
                    trades.append({
                        "action": "BUY",
                        "price": round(pos["buy_price"], 4),
                        "timestamp": snapped,
                        "original_date": pos["bought_at"],
                    })

    return jsonify({"candles": candles, "trades": trades})


@app.route("/api/positions")
def api_positions():
    """全ボットの保有ポジション + 未実現損益"""
    DATA_DIR = Path(__file__).parent.parent / "data"
    result = []

    # 保有銘柄のライブ価格を取得
    force = "refresh" in request.args
    all_tickers = []
    for fname in ["portfolio_long.json", "portfolio_medium.json", "portfolio_short.json", "portfolio_macro.json"]:
        d = fetch_github_json(fname, force_refresh=force)
        if d:
            all_tickers += list(d.get("positions", {}).keys())
    current_prices = fetch_live_prices(list(set(all_tickers)))

    for fname, label in [("portfolio_long.json", "長期"), ("portfolio_medium.json", "中期"), ("portfolio_short.json", "短期"), ("portfolio_macro.json", "マクロ")]:
        data = fetch_github_json(fname, force_refresh=force)
        if not data:
            continue
        try:
            balance = data.get("balance", 0)
            init    = data.get("initial_balance", 10000)
            positions = data.get("positions", {})
            stock_value = 0.0
            pos_list = []
            for ticker, p in positions.items():
                cur_price = current_prices.get(ticker, p["buy_price"])
                unrealized = (cur_price - p["buy_price"]) * p["shares"]
                unrealized_pct = (cur_price / p["buy_price"] - 1) * 100
                stock_value += cur_price * p["shares"]
                pos_list.append({
                    "ticker":        ticker,
                    "shares":        round(p["shares"], 6),
                    "buy_price":     round(p["buy_price"], 2),
                    "current_price": round(cur_price, 2),
                    "cost_basis":    round(p["cost_basis"], 2),
                    "unrealized":    round(unrealized, 2),
                    "unrealized_pct":round(unrealized_pct, 2),
                    "bought_at":     p.get("bought_at", ""),
                })
            total = balance + stock_value
            result.append({
                "bot":           label,
                "cash":          round(balance, 2),
                "stock_value":   round(stock_value, 2),
                "total_value":   round(total, 2),
                "initial":       init,
                "return_pct":    round((total / init - 1) * 100, 2),
                "positions":     pos_list,
            })
        except Exception as e:
            result.append({"bot": label, "error": str(e)})

    return jsonify(result)


def _to_jst(ts: str) -> str:
    """UTC ISO文字列 → JST表示文字列に変換"""
    from datetime import datetime, timezone, timedelta
    JST = timezone(timedelta(hours=9))
    try:
        # +00:00 や Z のどちらでも対応
        ts_clean = ts.replace("Z", "+00:00")
        if "+" not in ts_clean[10:] and ts_clean[-1] != "Z":
            ts_clean += "+00:00"
        dt = datetime.fromisoformat(ts_clean)
        return dt.astimezone(JST).strftime("%Y-%m-%d %H:%M JST")
    except Exception:
        return ts[:16] if len(ts) >= 16 else ts


@app.route("/api/trades")
def api_trades():
    """直近トレード一覧（GitHubのsummary.json優先、なければローカルDB）"""
    force = "refresh" in request.args
    summary = fetch_github_json("summary.json", force_refresh=force)
    rows = []

    if summary and summary.get("recent_trades"):
        # GitHub summary.json から全アクションを取得
        gh_trades = [t for t in summary["recent_trades"] if t.get("action")]

        # 重複排除キー: (coin, bot_type, 秒単位タイムスタンプ)
        def dedup_key(t):
            return (t.get("coin",""), t.get("bot_type",""), t.get("timestamp","")[:19])
        seen_keys = {dedup_key(t) for t in gh_trades}

        # ポートフォリオJSONのpositionsも確認してBUY漏れを補完
        for bot_key, fname in [("SHORT","portfolio_short.json"),("MEDIUM","portfolio_medium.json"),
                                ("LONG","portfolio_long.json"),("MACRO","portfolio_macro.json")]:
            pf = fetch_github_json(fname)
            if not pf:
                continue
            for ticker, pos in pf.get("positions", {}).items():
                ba = pos.get("bought_at", "")
                k = (ticker, bot_key, ba[:19])
                if ba and k not in seen_keys:
                    seen_keys.add(k)
                    gh_trades.append({
                        "timestamp": ba,
                        "action": "BUY",
                        "coin": ticker,
                        "price": pos.get("buy_price", 0),
                        "amount": pos.get("shares", 0),
                        "value_usd": pos.get("cost_basis", 0),
                        "balance_after": None,
                        "pnl": 0.0,
                        "reasoning": "(保有中)",
                        "confidence": None,
                        "risk_level": None,
                        "bot_type": bot_key,
                    })

        # タイムスタンプ降順 + JST変換
        gh_trades.sort(key=lambda t: t.get("timestamp",""), reverse=True)
        for t in gh_trades[:50]:
            t = dict(t)
            t["timestamp_jst"] = _to_jst(t.get("timestamp",""))
            rows.append(t)
    else:
        # フォールバック: ローカルDB
        if DB_PATH.exists():
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                SELECT timestamp, action, coin, price, amount, value_usd,
                       balance_after, pnl, reasoning, confidence, risk_level,
                       COALESCE(bot_type, 'SHORT') as bot_type
                FROM trades
                ORDER BY timestamp DESC LIMIT 50
            """)
            for r in cur.fetchall():
                t = dict(r)
                t["timestamp_jst"] = _to_jst(t.get("timestamp",""))
                rows.append(t)
            conn.close()
    return jsonify(rows)


@app.route("/api/snapshots")
def api_snapshots():
    """各銘柄の最新データをフラットなリストで返す"""
    if not DB_PATH.exists():
        return jsonify([])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT timestamp, raw_data, fear_greed_value, fear_greed_label
        FROM market_snapshots
        ORDER BY timestamp DESC
        LIMIT 10
    """)
    seen = {}
    for r in cur.fetchall():
        try:
            rd = json.loads(r["raw_data"] or "{}")
            fg_val   = r["fear_greed_value"]
            fg_label = r["fear_greed_label"]

            # medium/long: assets dict
            for ticker, info in rd.get("assets", {}).items():
                if info and ticker not in seen:
                    seen[ticker] = {
                        "coin":  ticker,
                        "price": info.get("price"),
                        "rsi":   info.get("rsi"),
                        "macd":  info.get("macd"),
                        "fear_greed_value": fg_val,
                        "fear_greed_label": fg_label,
                        "timestamp": r["timestamp"],
                    }
            # long: fundamentals dict
            for ticker, info in rd.get("fundamentals", {}).items():
                if info and ticker not in seen:
                    seen[ticker] = {
                        "coin":  ticker,
                        "price": info.get("price"),
                        "rsi":   None,
                        "macd":  None,
                        "pe":    info.get("pe_ratio"),
                        "fear_greed_value": None,
                        "fear_greed_label": None,
                        "timestamp": r["timestamp"],
                    }
            # short: technicals
            if rd.get("technicals") and rd.get("coin") and rd["coin"] not in seen:
                t = rd["technicals"]
                seen[rd["coin"]] = {
                    "coin":  rd["coin"],
                    "price": t.get("current_price"),
                    "rsi":   t.get("rsi"),
                    "macd":  t.get("macd"),
                    "fear_greed_value": fg_val,
                    "fear_greed_label": fg_label,
                    "timestamp": r["timestamp"],
                }
        except Exception:
            pass

    conn.close()
    return jsonify(list(seen.values()))


@app.route("/api/pnl_chart")
def api_pnl_chart():
    """累積損益チャート用データ"""
    if not DB_PATH.exists():
        return jsonify([])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT timestamp, pnl, balance_after
        FROM trades
        WHERE action='SELL'
        ORDER BY timestamp ASC
    """)
    rows = []
    cumulative = 0.0
    for r in cur.fetchall():
        cumulative += r["pnl"]
        rows.append({
            "timestamp": r["timestamp"][:10],
            "pnl":       round(r["pnl"], 2),
            "cumulative": round(cumulative, 2),
            "balance":   round(r["balance_after"], 2),
        })
    conn.close()
    return jsonify(rows)


@app.route("/api/manual_trade", methods=["POST"])
def api_manual_trade():
    """手動売買：portfolio JSON / trades.db / summary.json を更新して GitHub push"""
    import subprocess

    body = request.get_json() or {}
    action        = (body.get("action") or "").upper()
    coin          = (body.get("coin") or "").strip()
    bot_type      = (body.get("bot_type") or "SHORT").upper()
    note          = body.get("note") or "手動売買"
    is_short_sell = bool(body.get("is_short_sell", False))  # 空売り建て

    try:
        price      = float(body.get("price", 0))
        amount_usd = float(body.get("amount_usd", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "price / amount_usd は数値で指定してください"}), 400

    if action not in ("BUY", "SELL"):
        return jsonify({"error": "action は BUY または SELL"}), 400
    if not coin:
        return jsonify({"error": "coin を指定してください"}), 400
    if price <= 0:
        return jsonify({"error": "price > 0 が必要です"}), 400

    pf_map = {
        "SHORT": "portfolio_short.json", "MEDIUM": "portfolio_medium.json",
        "LONG":  "portfolio_long.json",  "MACRO":  "portfolio_macro.json",
    }
    pf_file = DATA_DIR / pf_map.get(bot_type, "portfolio_short.json")

    # ── portfolio JSON ロード ──────────────────────────────
    pf_data = {}
    if pf_file.exists():
        try:
            pf_data = json.loads(pf_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    balance          = float(pf_data.get("balance", 10000.0))
    initial          = float(pf_data.get("initial_balance", 10000.0))
    positions        = pf_data.get("positions", {})
    short_positions  = pf_data.get("short_positions", {})
    now_iso          = datetime.now(timezone.utc).isoformat()

    pnl      = 0.0
    shares   = 0.0
    is_short = False

    # 空売り中の銘柄をBUYした場合 → 自動で買戻し（カバー）
    is_cover = (action == "BUY" and coin in short_positions)

    if is_cover:
        # 買戻し（空売り決済）
        pos    = short_positions.pop(coin)
        shares = pos["shares"]
        pnl    = (pos["buy_price"] - price) * shares  # 下がれば+
        balance += pos["cost_basis"] + pnl
        amount_usd = shares * price
        is_short = True

    elif action == "BUY":
        if amount_usd <= 0:
            return jsonify({"error": "amount_usd > 0 が必要です（BUY）"}), 400
        if coin in positions:
            return jsonify({"error": f"既に {coin} を保有中"}), 400
        if balance < amount_usd:
            return jsonify({"error": f"残高不足（残高: ${balance:,.2f}）"}), 400
        shares   = amount_usd / price
        balance -= amount_usd
        positions[coin] = {
            "ticker": coin, "shares": shares, "buy_price": price,
            "bought_at": now_iso, "cost_basis": amount_usd, "peak_price": price,
        }

    elif is_short_sell:
        # 空売り建て
        invest = amount_usd if amount_usd > 0 else balance * 0.10
        if balance < invest:
            return jsonify({"error": f"残高不足（残高: ${balance:,.2f}）"}), 400
        if coin in short_positions:
            return jsonify({"error": f"既に {coin} を空売り中"}), 400
        shares      = invest / price
        balance    -= invest
        amount_usd  = invest
        short_positions[coin] = {
            "ticker": coin, "shares": shares, "buy_price": price,
            "bought_at": now_iso, "cost_basis": invest, "peak_price": price,
        }
        is_short = True

    else:  # 通常SELL（ロング決済）
        if coin not in positions:
            return jsonify({"error": f"{coin} を保有していません（空売りは「空売り」モードで）"}), 400
        pos        = positions.pop(coin)
        shares     = pos["shares"]
        sell_value = shares * price
        pnl        = sell_value - pos["cost_basis"]
        balance   += sell_value
        amount_usd = sell_value

    # ── portfolio JSON 保存 ────────────────────────────────
    pf_data.update({
        "balance": balance, "initial_balance": initial,
        "last_run": now_iso, "positions": positions,
        "short_positions": short_positions,
    })
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pf_file.write_text(json.dumps(pf_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── trades.db に記録 ──────────────────────────────────
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(DB_PATH)
            cur  = conn.cursor()
            cur.execute("""
                INSERT INTO trades
                  (timestamp, action, coin, price, amount, value_usd,
                   balance_after, pnl, reasoning, confidence, risk_level, bot_type, is_short)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (now_iso, action, coin, price, shares, amount_usd,
                  balance, pnl, note, 1.0, "MANUAL", bot_type, int(is_short)))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[MANUAL] DB error: {e}")

    # ── summary.json 再生成 ───────────────────────────────
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / "shared"))
        from summary import write_summary
        write_summary(bot_type)
    except Exception as e:
        print(f"[MANUAL] summary error: {e}")

    # ── GitHub push ───────────────────────────────────────
    git_root = str(Path(__file__).parent.parent.parent.parent.parent)
    pushed = False
    try:
        files = [
            f"saas-dev/projects/auto-invest/data/{pf_map.get(bot_type, 'portfolio_short.json')}",
            "saas-dev/projects/auto-invest/data/summary.json",
        ]
        subprocess.run(["git", "add"] + files, cwd=git_root, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m",
             f"manual: {action} {coin} @ ${price:.2f} [{bot_type}] [skip ci]"],
            cwd=git_root, check=True, capture_output=True,
        )
        subprocess.run(["git", "pull", "--rebase", "-X", "theirs"],
                       cwd=git_root, capture_output=True)
        subprocess.run(["git", "push"], cwd=git_root, check=True, capture_output=True)
        pushed = True
    except Exception as e:
        print(f"[MANUAL] git error: {e}")

    # ── GitHub キャッシュ無効化 ───────────────────────────
    global _github_cache
    _github_cache.clear()

    return jsonify({
        "ok":         True,
        "pushed":     pushed,
        "action":     action,
        "coin":       coin,
        "bot_type":   bot_type,
        "price":      price,
        "shares":     round(shares, 6),
        "amount_usd": round(amount_usd, 2),
        "pnl":        round(pnl, 2),
        "balance":    round(balance, 2),
        "is_short":   is_short,
    })


@app.route("/api/git_pull", methods=["POST"])
def api_git_pull():
    """git pull してローカルDBをリモートの最新状態に同期する"""
    import subprocess
    repo_root = Path(__file__).parent.parent.parent.parent.parent  # ai-holdings/
    try:
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return jsonify({
            "ok": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        })
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "timeout"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/trigger_bots", methods=["POST"])
def api_trigger_bots():
    """GitHub Actions の全ボットを手動トリガー"""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return jsonify({"error": "GITHUB_TOKEN not set"}), 500

    workflows = ["bot-short.yml", "bot-medium.yml", "bot-long.yml", "bot-macro.yml"]
    results = {}
    for wf in workflows:
        try:
            r = requests.post(
                f"https://api.github.com/repos/ryuu321/ai-holdings/actions/workflows/{wf}/dispatches",
                headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"},
                json={"ref": "master"},
                timeout=10,
            )
            results[wf] = r.status_code  # 204 = success
        except Exception as e:
            results[wf] = str(e)
    return jsonify({"results": results})


# ─────────────────────────────────────────────
# フロントエンド（シングルページ）
# ─────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI HOLDINGS | 投資ダッシュボード</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0b0e14;
    --card: rgba(23, 27, 38, 0.7);
    --border: rgba(255, 255, 255, 0.08);
    --text: #ffffff;
    --muted: #94a3b8;
    --accent: #6366f1;
    --green: #10b981;
    --red: #f43f5e;
    --glass: rgba(255, 255, 255, 0.03);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: radial-gradient(circle at top right, #1e1b4b, #0b0e14 40%), #0b0e14;
    color: var(--text);
    font-family: 'Inter', 'Noto Sans JP', sans-serif;
    line-height: 1.5;
    overflow-x: hidden;
  }

  @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.4; } 100% { opacity: 1; } }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

  header {
    background: rgba(11, 14, 20, 0.8);
    backdrop-filter: blur(20px);
    border-bottom: 2px solid var(--accent);
    padding: 16px 40px;
    display: flex;
    align-items: center;
    position: sticky; top: 0; z-index: 1000;
  }

  header h1 {
    font-size: 20px; font-weight: 900; letter-spacing: 2px;
    background: linear-gradient(to right, #6366f1, #00d2ff);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }

  .live-dot {
    width: 8px; height: 8px; background: var(--green); border-radius: 50%;
    margin-right: 8px; display: inline-block;
    box-shadow: 0 0 10px var(--green); animation: pulse 2s infinite;
  }

  .status-tag {
    background: var(--glass); border: 1px solid var(--border);
    padding: 4px 12px; border-radius: 99px; font-size: 11px; font-weight: 600;
    color: var(--muted); margin-left: 16px; display: flex; align-items: center;
  }

  .container { max-width: 1440px; margin: 0 auto; padding: 32px; }

  .grid { display: grid; gap: 24px; }
  .grid-4 { grid-template-columns: repeat(4, 1fr); }
  @media (max-width: 1100px) { .grid-4 { grid-template-columns: repeat(2, 1fr); } }

  .card {
    background: var(--card); backdrop-filter: blur(10px);
    border: 1px solid var(--border); border-radius: 20px;
    padding: 24px; transition: all 0.3s ease;
    animation: fadeIn 0.5s ease-out;
  }
  .card:hover { border-color: rgba(99, 102, 241, 0.4); transform: translateY(-4px); }

  .stat-label { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; }
  .stat { font-size: 32px; font-weight: 800; letter-spacing: -0.04em; margin: 4px 0; }
  .stat-sub { font-size: 12px; color: var(--muted); }

  .green { color: var(--green); }
  .red { color: var(--red); }

  .section-title { font-size: 20px; font-weight: 800; margin: 48px 0 24px; display: flex; align-items: center; gap: 12px; }
  .section-title::after { content: ''; height: 1px; flex-grow: 1; background: var(--border); }

  table { width: 100%; border-collapse: separate; border-spacing: 0 4px; }
  th { text-align: left; color: var(--muted); font-size: 10px; padding: 8px 16px; text-transform: uppercase; }
  td { padding: 12px 16px; background: rgba(255, 255, 255, 0.02); border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
  td:first-child { border-left: 1px solid var(--border); border-top-left-radius: 8px; border-bottom-left-radius: 8px; }
  td:last-child { border-right: 1px solid var(--border); border-top-right-radius: 8px; border-bottom-right-radius: 8px; }

  .badge { padding: 3px 8px; border-radius: 6px; font-size: 10px; font-weight: 700; border: 1px solid transparent; }
  .badge-buy { background: rgba(16, 185, 129, 0.1); color: var(--green); border-color: rgba(16, 185, 129, 0.2); }
  .badge-sell { background: rgba(244, 63, 94, 0.1); color: var(--red); border-color: rgba(244, 63, 94, 0.2); }
  .badge-hold { background: rgba(148, 163, 184, 0.1); color: #94a3b8; border-color: rgba(148, 163, 184, 0.2); }
  
  .badge-short { color: #60a5fa; background: rgba(59, 130, 246, 0.1); border-color: rgba(59, 130, 246, 0.2); }
  .badge-medium { color: #c084fc; background: rgba(168, 85, 247, 0.1); border-color: rgba(168, 85, 247, 0.2); }
  .badge-long { color: #fb923c; background: rgba(249, 115, 22, 0.1); border-color: rgba(249, 115, 22, 0.2); }
  .badge-macro { color: #f472b6; background: rgba(236, 72, 153, 0.1); border-color: rgba(236, 72, 153, 0.2); }

  .refresh-btn {
    background: var(--accent); color: white; border: none; padding: 10px 20px;
    border-radius: 12px; cursor: pointer; font-size: 13px; font-weight: 700;
    box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3); transition: all 0.2s;
  }
  .refresh-btn:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4); }

  .pos-card {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .chart-mini { height: 80px; width: 100%; }

  .interval-selector {
    display: flex; gap: 8px; margin-left: auto;
  }
  .interval-btn {
    background: var(--glass); border: 1px solid var(--border); color: var(--muted);
    padding: 6px 12px; border-radius: 8px; font-size: 11px; cursor: pointer; font-weight: 600;
    transition: all 0.2s;
  }
  .interval-btn:hover { background: rgba(255,255,255,0.1); border-color: var(--muted); }
  .interval-btn.active { background: var(--accent); color: white; border-color: var(--accent); }

  /* ── 手動売買モーダル ───────────────────── */
  .modal-overlay {
    display: none; position: fixed; inset: 0; z-index: 9999;
    background: rgba(0,0,0,0.7); backdrop-filter: blur(6px);
    align-items: center; justify-content: center;
  }
  .modal-overlay.open { display: flex; }
  .modal {
    background: #131720; border: 1px solid rgba(99,102,241,0.4);
    border-radius: 24px; padding: 32px; width: 420px; max-width: 95vw;
    box-shadow: 0 20px 60px rgba(0,0,0,0.6);
    animation: fadeIn 0.2s ease-out;
  }
  .modal h2 { font-size: 18px; font-weight: 800; margin-bottom: 24px; }
  .modal label { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; display: block; margin-bottom: 6px; margin-top: 16px; }
  .modal input, .modal select {
    width: 100%; background: rgba(255,255,255,0.05); border: 1px solid var(--border);
    color: var(--text); padding: 10px 14px; border-radius: 10px; font-size: 14px;
    outline: none; transition: border-color 0.2s;
  }
  .modal input:focus, .modal select:focus { border-color: var(--accent); }
  .modal input::placeholder { color: var(--muted); }
  .action-toggle { display: flex; gap: 8px; margin-bottom: 4px; }
  .action-btn {
    flex: 1; padding: 10px; border-radius: 10px; border: 1px solid var(--border);
    background: var(--glass); color: var(--muted); font-weight: 700; font-size: 14px;
    cursor: pointer; transition: all 0.2s;
  }
  .action-btn.buy.active  { background: rgba(16,185,129,0.15); color: var(--green); border-color: rgba(16,185,129,0.4); }
  .action-btn.sell.active { background: rgba(244,63,94,0.15);  color: var(--red);   border-color: rgba(244,63,94,0.4); }
  .price-row { display: flex; gap: 8px; }
  .price-row input { flex: 1; }
  .fetch-price-btn {
    background: var(--glass); border: 1px solid var(--border); color: var(--muted);
    padding: 10px 12px; border-radius: 10px; font-size: 11px; cursor: pointer;
    white-space: nowrap; transition: all 0.2s; font-weight: 600;
  }
  .fetch-price-btn:hover { border-color: var(--accent); color: var(--accent); }
  .modal-footer { display: flex; gap: 12px; margin-top: 24px; }
  .submit-btn {
    flex: 1; padding: 12px; border-radius: 12px; border: none;
    font-weight: 800; font-size: 15px; cursor: pointer; transition: all 0.2s;
    background: var(--accent); color: white;
    box-shadow: 0 4px 12px rgba(99,102,241,0.3);
  }
  .submit-btn:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(99,102,241,0.4); }
  .submit-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
  .cancel-btn {
    padding: 12px 20px; border-radius: 12px; border: 1px solid var(--border);
    background: transparent; color: var(--muted); font-size: 14px; cursor: pointer;
  }
  .modal-msg { margin-top: 12px; font-size: 13px; text-align: center; min-height: 20px; }
</style>
</head>
<body>

<header>
  <h1>AI HOLDINGS</h1>
  <div class="status-tag"><span class="live-dot"></span><span id="last-update">接続中...</span></div>
  <div id="bot-last-run" style="margin-left:16px; display:flex; align-items:center;"></div>
  <a href="/trade" style="margin-left:auto; text-decoration:none;">
    <button class="refresh-btn" style="background:rgba(251,191,36,0.12);border-color:rgba(251,191,36,0.4);color:#fbbf24">📈 トレード</button>
  </a>
  <button class="refresh-btn" style="margin-left:8px" onclick="loadAll()">画面更新</button>
  <button class="refresh-btn" id="trigger-btn" style="margin-left:8px; background:rgba(16,185,129,0.15); border-color:rgba(16,185,129,0.4); color:#10b981" onclick="triggerBots()">▶ ボット実行</button>
  <button class="refresh-btn" style="margin-left:8px; background:rgba(251,191,36,0.12); border-color:rgba(251,191,36,0.4); color:#fbbf24" onclick="openTradeModal()">手動売買</button>
  <a href="https://t.me/+yUiqVJi2uNFiOTA1" target="_blank" style="margin-left:8px; text-decoration:none;">
    <button class="refresh-btn" style="background:rgba(32,178,226,0.15); border-color:rgba(32,178,226,0.4); color:#20b2e2">📊 Telegram</button>
  </a>
</header>

<!-- 手動売買モーダル -->
<div class="modal-overlay" id="trade-modal" onclick="e => { if(e.target===this) closeTradeModal(); }">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>✏️ 手動売買</h2>

    <div class="action-toggle">
      <button class="action-btn buy active" id="btn-buy"  onclick="setAction('BUY')">BUY  買い</button>
      <button class="action-btn sell"       id="btn-sell" onclick="setAction('SELL')">SELL  売り</button>
    </div>

    <label>ポートフォリオ</label>
    <select id="m-bottype">
      <option value="SHORT">短期 (SHORT)</option>
      <option value="MEDIUM">中期 (MEDIUM)</option>
      <option value="LONG">長期 (LONG)</option>
      <option value="MACRO">マクロ (MACRO)</option>
    </select>

    <label>銘柄 (ティッカー)</label>
    <input id="m-coin" type="text" placeholder="例: MSFT, bitcoin, AAPL" autocomplete="off"
           list="coin-list" oninput="onCoinChange()">
    <datalist id="coin-list">
      <option value="bitcoin"><option value="MSFT"><option value="AAPL">
      <option value="SPY"><option value="QQQ"><option value="NVDA">
      <option value="AMZN"><option value="GOOGL"><option value="META">
    </datalist>

    <label>価格 (USD)</label>
    <div class="price-row">
      <input id="m-price" type="number" step="0.01" min="0.01" placeholder="0.00">
      <button class="fetch-price-btn" onclick="fetchLivePrice()">現在値取得</button>
    </div>

    <div id="sell-info" style="display:none; margin-top:12px;">
      <label>売却対象ポジション</label>
      <div id="sell-pos-info" style="font-size:13px; color:var(--muted); padding:10px 14px; background:rgba(255,255,255,0.03); border:1px solid var(--border); border-radius:10px;">
        銘柄を入力してください
      </div>
    </div>

    <div id="buy-amount" style="">
      <label>金額 (USD)</label>
      <input id="m-amount" type="number" step="1" min="1" placeholder="0">
    </div>

    <label>メモ（任意）</label>
    <input id="m-note" type="text" placeholder="手動売買">

    <div class="modal-msg" id="modal-msg"></div>
    <div class="modal-footer">
      <button class="cancel-btn" onclick="closeTradeModal()">キャンセル</button>
      <button class="submit-btn" id="submit-btn" onclick="submitTrade()">実行</button>
    </div>
  </div>
</div>

<div class="container">
  <div class="grid grid-4" style="margin-bottom: 40px;">
    <div class="card"><div class="stat-label">確定損益 (Realized)</div><div class="stat" id="kpi-pnl">--</div><div class="stat-sub">決済済みの利益合計</div></div>
    <div class="card"><div class="stat-label">未実現損益 (Floating)</div><div class="stat" id="kpi-unrealized">--</div><div class="stat-sub">保有銘柄の評価損益</div></div>
    <div class="card"><div class="stat-label">勝率 (Win Rate)</div><div class="stat" id="kpi-winrate">--</div><div class="stat-sub">SELL取引の成功率</div></div>
    <div class="card"><div class="stat-label">総取引数 (Trades)</div><div class="stat" id="kpi-trades">--</div><div class="stat-sub">BUY / SELL 実行数</div></div>
  </div>

  <div class="section-title">
    保有ポジション
    <div class="interval-selector">
      <button class="interval-btn" onclick="updateInterval('5m')">5分</button>
      <button class="interval-btn" onclick="updateInterval('15m')">15分</button>
      <button class="interval-btn" onclick="updateInterval('30m')">30分</button>
      <button class="interval-btn active" onclick="updateInterval('1h')">1時間</button>
      <button class="interval-btn" onclick="updateInterval('1d')">1日</button>
    </div>
  </div>
  <div id="positions-section" class="grid" style="grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));"></div>

  <div class="grid" style="grid-template-columns: 1.6fr 1fr; margin-top: 48px;">
    <div>
      <div class="section-title">トレード履歴</div>
      <div class="card" style="padding:16px; overflow-x: auto;">
        <table style="font-size: 13px;">
          <thead><tr><th>日時</th><th>ボット</th><th>売買</th><th>銘柄</th><th>価格</th><th>株数</th><th>約定額</th><th>確定損益</th></tr></thead>
          <tbody id="trades-body"></tbody>
          <tfoot id="trades-foot"></tfoot>
        </table>
      </div>
    </div>
    <div>
      <div class="section-title">市場コンディション</div>
      <div class="card" style="padding:16px">
        <table style="font-size: 13px;">
          <thead><tr><th>銘柄</th><th>現在価格</th><th>RSI</th><th>F&G</th></tr></thead>
          <tbody id="snapshot-body"></tbody>
        </table>
      </div>
    </div>
  </div>

  <div class="section-title">累積損益の推移</div>
  <div class="card">
    <div style="height: 300px;"><canvas id="pnl-chart"></canvas></div>
  </div>
</div>

<script>
let pnlChart = null;
const sparklineCharts = {};
let cachedSummary = null;

// ── マーカー画像生成（キャッシュ付き）────────────────────
const _mk = {};
function markerImg(shape, fill, brd, sz=18) {
  const k = `${shape}|${fill}|${brd}`;
  if (_mk[k]) return _mk[k];
  const cv = document.createElement('canvas');
  cv.width = cv.height = sz;
  const g = cv.getContext('2d'), m = 1.5;
  if (shape === 'up' || shape === 'dn') {
    g.beginPath();
    if (shape === 'up') { g.moveTo(sz/2,m); g.lineTo(sz-m,sz-m); g.lineTo(m,sz-m); }
    else               { g.moveTo(sz/2,sz-m); g.lineTo(sz-m,m); g.lineTo(m,m); }
    g.closePath(); g.fillStyle=fill; g.fill(); g.strokeStyle=brd; g.lineWidth=2; g.stroke();
  } else {
    const ch = { star:'★', club:'♣' }[shape] || '●';
    g.font = `bold ${sz+2}px serif`;
    g.textAlign='center'; g.textBaseline='middle';
    g.fillStyle=brd; g.fillText(ch, sz/2+0.8, sz/2+0.8); // shadow=border
    g.fillStyle=fill; g.fillText(ch, sz/2, sz/2);
  }
  const img = new Image(); img.src = cv.toDataURL(); _mk[k] = img; return img;
}
function tradeMarker(t) {
  const botFillMap = { SHORT:'#60a5fa', MEDIUM:'#10b981', LONG:'#fb923c', MACRO:'#f472b6' };
  const fill = botFillMap[t.bot_type] || '#6366f1';
  const brd  = t.is_manual ? '#f43f5e' : '#ffffff';
  let shape;
  if (t.action === 'BUY')        shape = t.is_short ? 'dn' : 'up';   // ショートBUYは将来用
  else if (t.pnl >= 0)           shape = t.is_short ? 'club' : 'star';
  else                           shape = 'dn';
  return markerImg(shape, fill, brd);
}

function fmt(n, digits=2) {
  if (n == null || isNaN(n)) return '--';
  return Number(n).toLocaleString('ja-JP', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function toJST(utcStr) {
  if (!utcStr) return '';
  try {
    const d = new Date(utcStr);
    return d.toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo',
      month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit' }) + ' JST';
  } catch(e) { return utcStr.substring(5,16); }
}

async function renderStats(s) {
  const stats = s.stats || {};
  const pnl = stats.realized_pnl || 0;
  const pnlEl = document.getElementById('kpi-pnl');
  pnlEl.textContent = (pnl >= 0 ? '+' : '') + '$' + fmt(pnl);
  pnlEl.className = 'stat ' + (pnl >= 0 ? 'green' : 'red');
  document.getElementById('kpi-winrate').textContent = (stats.win_rate || 0) + '%';
  document.getElementById('kpi-trades').textContent = (stats.total_buys || 0) + ' / ' + (stats.total_sells || 0);
  if (s.updated_at) {
    const d = new Date(s.updated_at);
    const jstStr = d.toLocaleString('ja-JP', {
      timeZone: 'Asia/Tokyo', year:'numeric', month:'2-digit', day:'2-digit',
      hour:'2-digit', minute:'2-digit'
    });
    document.getElementById('last-update').textContent = '最終実行: ' + jstStr + ' JST';
  }
  // 各ボットの最終実行時刻（portfolio JSONのlast_runから取得）
  const botNames = { SHORT: '短期', MEDIUM: '中期', LONG: '長期', MACRO: 'マクロ', ATTACK: '攻撃型', VOLT: 'ボラ型' };
  const botRunEl = document.getElementById('bot-last-run');
  if (botRunEl) {
    const portfolios = s.portfolios || {};
    botRunEl.innerHTML = Object.entries(botNames).map(([k, name]) => {
      const pf = portfolios[k] || {};
      const t = pf.last_run;
      const timeStr = t ? toJST(t) : '未実行';
      return `<span style="margin-right:12px; font-size:11px; color:var(--muted)">${name}: <span style="color:var(--text)">${timeStr}</span></span>`;
    }).join('');
  }
}

async function renderPositions(s, livePrices = {}) {
  const portfolios = s.portfolios || {};
  const container = document.getElementById('positions-section');
  
  let html = '';
  let totalFloating = 0;
  const botInfo = {
    LONG:   { label: '長期戦略', class: 'badge-long' },
    MEDIUM: { label: '中期戦略', class: 'badge-medium' },
    SHORT:  { label: '短期戦略', class: 'badge-short' },
    MACRO:  { label: 'マクロ戦略', class: 'badge-macro' },
    ATTACK: { label: '攻撃型トレンド', class: 'badge-short' },
    VOLT:   { label: 'ボラ型', class: 'badge-medium' }
  };

  Object.entries(portfolios).forEach(([botKey, data]) => {
    Object.entries(data.positions || {}).forEach(([ticker, p]) => {
      const curPrice = livePrices[ticker] || p.buy_price;
      const profit = (curPrice - p.buy_price) * p.shares;
      const profitPct = (curPrice / p.buy_price - 1) * 100;
      totalFloating += profit;
      const c = profit >= 0 ? 'green' : 'red';
      const safeId = `${botKey}_${ticker.replace(/[^a-z0-9]/gi, '_')}`;
      const bot = botInfo[botKey] || { label: botKey, class: '' };

      html += `
        <div class="pos-card">
          <div style="display:flex; justify-content:space-between; align-items: flex-start;">
            <div>
              <div style="display:flex; align-items:center; gap:8px; margin-bottom:4px;">
                <span style="font-size:18px; font-weight:900;">${ticker}</span>
                <span class="badge ${bot.class}">${bot.label}</span>
              </div>
              <div style="font-size:24px; font-weight:800; font-family:monospace;">$${fmt(curPrice)}</div>
              <div class="${c}" style="font-weight:700; font-size:14px;">
                ${profit >= 0 ? '+' : ''}$${fmt(profit)} (${profit>=0?'+':''}${fmt(profitPct)}%)
              </div>
            </div>
            <div style="text-align:right; font-size:11px; color:var(--muted); line-height:1.4;">
              <div>取得: $${fmt(p.buy_price)}</div>
              <div>数量: ${fmt(p.shares, 4)}</div>
              <div style="margin-top:6px; color:rgba(255,255,255,0.8)">評価額: $${fmt(curPrice * p.shares)}</div>
              ${p.bought_at ? `<div style="margin-top:4px; font-size:10px; color:var(--muted)">${toJST(p.bought_at)}</div>` : ''}
            </div>
          </div>
          <div class="chart-mini"><canvas id="spark_${safeId}"></canvas></div>
        </div>
      `;
    });
  });

  container.innerHTML = html || '<div class="card" style="grid-column: 1/-1; text-align:center; padding:40px; color:var(--muted)">現在、保有ポジションはありません</div>';
  const floatingEl = document.getElementById('kpi-unrealized');
  floatingEl.textContent = (totalFloating >= 0 ? '+' : '') + '$' + fmt(totalFloating);
  floatingEl.className = 'stat ' + (totalFloating >= 0 ? 'green' : 'red');

  Object.entries(portfolios).forEach(([botKey, data]) => {
    Object.keys(data.positions || {}).forEach(ticker => {
      const safeId = `${botKey}_${ticker.replace(/[^a-z0-9]/gi, '_')}`;
      drawSparkline(botKey, ticker, `spark_${safeId}`);
    });
  });
}

let currentInterval = '1h';

function updateInterval(val) {
  if (currentInterval === val) return;
  currentInterval = val;
  document.querySelectorAll('.interval-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('onclick').includes(`'${val}'`));
  });
  // 全体の再描画ではなく、チャートのみを更新して高速化
  if (cachedSummary && cachedSummary.portfolios) {
    Object.entries(cachedSummary.portfolios).forEach(([botKey, data]) => {
      Object.keys(data.positions || {}).forEach(ticker => {
        const safeId = `${botKey}_${ticker.replace(/[^a-z0-9]/gi, '_')}`;
        drawSparkline(botKey, ticker, `spark_${safeId}`);
      });
    });
  }
}

async function drawSparkline(botKey, ticker, canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.style.opacity = '0.5';
  try {
    const data = await fetch(`/api/history/${encodeURIComponent(ticker)}?interval=${currentInterval}&bot_type=${botKey}`).then(r=>r.json());
    if (!data.candles || data.candles.length === 0) return;

    const botFillMap = { SHORT:'#60a5fa', MEDIUM:'#10b981', LONG:'#fb923c', MACRO:'#f472b6' };
    const themeColor = botFillMap[botKey] || '#6366f1';

    const labels = data.candles.map(c => c.date);
    const prices = data.candles.map(c => c.price);

    const ptRadius = prices.map(() => 0);
    const ptStyle  = prices.map(() => false);
    const tradeByIdx = {};

    data.trades.forEach(t => {
      let idx = labels.indexOf(t.timestamp);
      if (idx < 0) {
        for (let i = labels.length - 1; i >= 0; i--) {
          if (labels[i] <= t.timestamp) { idx = i; break; }
        }
      }
      if (idx >= 0) {
        ptRadius[idx] = 9;
        ptStyle[idx]  = tradeMarker(t);
        tradeByIdx[idx] = t;
      }
    });

    if (sparklineCharts[canvasId]) sparklineCharts[canvasId].destroy();
    sparklineCharts[canvasId] = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels,
        datasets: [{
          data: prices,
          borderColor: 'rgba(255,255,255,0.25)',
          borderWidth: 1,
          pointRadius: ptRadius,
          pointHoverRadius: ptRadius.map(r => r > 0 ? r + 4 : 0),
          pointHitRadius: ptRadius.map(r => r > 0 ? 14 : 0),
          pointStyle: ptStyle,
          fill: false,
          tension: 0.3
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        interaction: { mode: 'nearest', intersect: true },
        plugins: {
          legend: { display: false },
          tooltip: {
            enabled: true,
            backgroundColor: 'rgba(0,0,0,0.85)',
            titleColor: themeColor,
            callbacks: {
              title: (items) => {
                const t = tradeByIdx[items[0].dataIndex];
                return t ? `${t.action==='BUY'?'▲ BUY':'▼ SELL'}  ${labels[items[0].dataIndex]}` : labels[items[0].dataIndex];
              },
              label: (ctx) => {
                const t = tradeByIdx[ctx.dataIndex];
                if (!t) return `$${fmt(ctx.parsed.y)}`;
                const lines = [
                  `価格: $${fmt(ctx.parsed.y)}`,
                  `株数: ${fmt(t.amount, 4)}`,
                  `約定額: $${fmt(t.value_usd)}`,
                ];
                if (t.action === 'SELL') {
                  lines.push(`確定損益: ${t.pnl>=0?'+':''}$${fmt(t.pnl)}`);
                }
                return lines;
              }
            }
          }
        },
        scales: {
          x: { display: false },
          y: { display: false }
        }
      }
    });
  } catch(e) { console.error(e); }
  canvas.style.opacity = '1';
}

async function loadAll() {
  const btn = document.querySelector('.refresh-btn');
  const originalText = btn.innerText;
  btn.innerText = '同期中...';
  try {
    // まず git pull でローカルDBをリモートの最新状態に同期
    await fetch('/api/git_pull', { method: 'POST' }).catch(() => {});
    btn.innerText = '更新中...';
    // 並列実行で高速化
    const [s, pricesRes] = await Promise.all([
      fetch('/api/summary_local?refresh=1').then(r=>r.json()),
      fetch('/api/live_prices').then(r=>r.json()).catch(()=>({prices:{}}))
    ]);
    
    cachedSummary = s;
    const livePrices = pricesRes.prices || {};
    
    await renderStats(s);
    await renderPositions(s, livePrices);
    
    const botClasses = { SHORT: 'badge-short', MEDIUM: 'badge-medium', LONG: 'badge-long', MACRO: 'badge-macro' };
    // 直近トレードはGitHub最新データ(/api/trades)から取得
    const trades = await fetch('/api/trades').then(r=>r.json()).catch(()=>[]);
    const shown = trades.slice(0, 15);
    document.getElementById('trades-body').innerHTML = shown.map(t => {
      const isSell = t.action === 'SELL';
      // 決済行の色: 利益=白、損失=グレー
      const pnlColor = isSell ? (t.pnl >= 0 ? '#ffffff' : '#64748b') : 'var(--muted)';
      const rowOpacity = isSell && t.pnl < 0 ? 'opacity:0.65;' : '';
      return `<tr style="${rowOpacity}">
        <td style="font-size:11px; color:var(--muted)">${t.timestamp_jst || t.timestamp.substring(5,16).replace('T',' ')}</td>
        <td><span class="badge ${botClasses[t.bot_type] || ''}">${t.bot_type==='LONG'?'長期':t.bot_type==='MEDIUM'?'中期':t.bot_type==='SHORT'?'短期':'マクロ'}</span></td>
        <td><span class="badge ${t.action==='BUY'?'badge-buy':t.action==='SELL'?'badge-sell':'badge-hold'}">${t.action==='BUY'?'買い':t.action==='SELL'?'売り':'様子見'}</span></td>
        <td style="font-weight:700">${t.coin}</td>
        <td style="font-family:monospace">$${fmt(t.price)}</td>
        <td style="font-family:monospace; color:var(--muted); font-size:11px">${t.amount ? fmt(t.amount,4) : '--'}</td>
        <td style="font-family:monospace; font-size:11px">$${t.value_usd ? fmt(t.value_usd) : '--'}</td>
        <td style="font-weight:700; color:${pnlColor}">${isSell ? (t.pnl>=0?'+':'')+'$'+fmt(t.pnl) : '--'}</td>
      </tr>`;
    }).join('');
    // 表示中トレードの確定損益合計
    const totalPnl = shown.filter(t=>t.action==='SELL').reduce((s,t)=>s+(t.pnl||0), 0);
    document.getElementById('trades-foot').innerHTML = `
      <tr style="border-top: 1px solid rgba(255,255,255,0.15);">
        <td colspan="7" style="font-size:11px; color:var(--muted); padding-top:10px;">表示中の確定損益合計</td>
        <td style="font-weight:800; font-size:13px; padding-top:10px; color:${totalPnl>=0?'#ffffff':'#64748b'}">${totalPnl>=0?'+':''}$${fmt(totalPnl)}</td>
      </tr>`;

    const snaps = await fetch('/api/snapshots').then(r=>r.json());
    document.getElementById('snapshot-body').innerHTML = snaps.map(sn => `
      <tr>
        <td style="font-weight:700">${sn.coin}</td>
        <td style="font-family:monospace">$${fmt(sn.price)}</td>
        <td class="${sn.rsi>70?'red':sn.rsi<30?'green':''}" style="font-weight:700">${fmt(sn.rsi,1)}</td>
        <td>${sn.fear_greed_value ? sn.fear_greed_value + ' (' + sn.fear_greed_label + ')' : '--'}</td>
      </tr>`).join('');

    const pData = await fetch('/api/pnl_chart').then(r=>r.json());
    const ctx = document.getElementById('pnl-chart').getContext('2d');
    if (pnlChart) pnlChart.destroy();
    pnlChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: pData.map(d => d.timestamp),
        datasets: [{ data: pData.map(d => d.cumulative), borderColor: '#6366f1', borderWidth: 3, backgroundColor: 'rgba(99, 102, 241, 0.1)', fill: true, tension: 0.3, pointRadius: 4 }]
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#64748b' }, grid: { display: false } }, y: { ticks: { color: '#64748b' }, grid: { color: 'rgba(255,255,255,0.05)' } } } }
    });
  } catch(e) { console.error(e); }
  btn.innerText = originalText;
}

async function triggerBots() {
  const btn = document.getElementById('trigger-btn');
  btn.innerText = '実行中...';
  btn.disabled = true;
  try {
    const res = await fetch('/api/trigger_bots', { method: 'POST' }).then(r => r.json());
    const ok = Object.values(res.results || {}).every(v => v === 204);
    btn.innerText = ok ? '✓ 起動完了' : '⚠ 一部失敗';
    setTimeout(() => {
      btn.innerText = '▶ ボット実行';
      btn.disabled = false;
      // 30秒後に画面更新（Actions完了を待つ）
      setTimeout(loadAll, 30000);
    }, 3000);
  } catch(e) {
    btn.innerText = 'エラー';
    btn.disabled = false;
  }
}

// ── 手動売買モーダル ─────────────────────────────
let currentAction = 'BUY';

function openTradeModal() {
  document.getElementById('trade-modal').classList.add('open');
  document.getElementById('modal-msg').textContent = '';
}
function closeTradeModal() {
  document.getElementById('trade-modal').classList.remove('open');
}
// overlay クリックで閉じる
document.getElementById('trade-modal').addEventListener('click', function(e) {
  if (e.target === this) closeTradeModal();
});

function setAction(a) {
  currentAction = a;
  document.getElementById('btn-buy').classList.toggle('active', a === 'BUY');
  document.getElementById('btn-sell').classList.toggle('active', a === 'SELL');
  document.getElementById('sell-info').style.display = a === 'SELL' ? '' : 'none';
  document.getElementById('buy-amount').style.display = a === 'BUY'  ? '' : 'none';
  document.getElementById('submit-btn').style.background =
    a === 'BUY' ? 'var(--green)' : 'var(--red)';
  onCoinChange();
}

function onCoinChange() {
  if (currentAction !== 'SELL') return;
  const coin    = (document.getElementById('m-coin').value || '').trim().toUpperCase();
  const botType = document.getElementById('m-bottype').value;
  const el      = document.getElementById('sell-pos-info');
  if (!cachedSummary) { el.textContent = '-- (データ未ロード)'; return; }
  const pf = (cachedSummary.portfolios || {})[botType] || {};
  // bitcoin は小文字キーで保存されている場合も考慮
  const key = Object.keys(pf.positions || {}).find(k => k.toUpperCase() === coin || k === coin);
  if (!key) { el.textContent = `${coin || '...'} は ${botType} に保有なし`; return; }
  const p = pf.positions[key];
  el.innerHTML = `<strong>${key}</strong> &nbsp; ${fmt(p.shares,6)} 株 &nbsp; 取得: $${fmt(p.buy_price)} &nbsp; コスト: $${fmt(p.cost_basis)}`;
}

async function fetchLivePrice() {
  const coin = (document.getElementById('m-coin').value || '').trim();
  if (!coin) { alert('銘柄を入力してください'); return; }
  const btn = document.querySelector('.fetch-price-btn');
  btn.textContent = '取得中...';
  try {
    // bitcoin / btc など暗号資産は coin として渡す
    const isCrypto = ['bitcoin','btc','btc-usd','ethereum','eth'].includes(coin.toLowerCase());
    const ticker   = isCrypto ? coin.toLowerCase() : coin.toUpperCase();
    const res = await fetch(`/api/history/${encodeURIComponent(ticker)}?interval=5m`).then(r => r.json());
    const last = res.candles && res.candles.length > 0 ? res.candles[res.candles.length - 1].price : null;
    if (last) {
      document.getElementById('m-price').value = last.toFixed(2);
      btn.textContent = `✓ $${fmt(last)}`;
      setTimeout(() => { btn.textContent = '現在値取得'; }, 3000);
    } else {
      btn.textContent = '取得失敗';
      setTimeout(() => { btn.textContent = '現在値取得'; }, 2000);
    }
  } catch(e) {
    btn.textContent = '取得失敗';
    setTimeout(() => { btn.textContent = '現在値取得'; }, 2000);
  }
}

async function submitTrade() {
  const coin    = (document.getElementById('m-coin').value || '').trim();
  const botType = document.getElementById('m-bottype').value;
  const price   = parseFloat(document.getElementById('m-price').value || '0');
  const note    = document.getElementById('m-note').value || '手動売買';
  const msgEl   = document.getElementById('modal-msg');
  const btn     = document.getElementById('submit-btn');

  if (!coin)    { msgEl.style.color='var(--red)'; msgEl.textContent = '銘柄を入力してください'; return; }
  if (!price)   { msgEl.style.color='var(--red)'; msgEl.textContent = '価格を入力してください'; return; }

  let body = { action: currentAction, coin, bot_type: botType, price, note };
  if (currentAction === 'BUY') {
    const amt = parseFloat(document.getElementById('m-amount').value || '0');
    if (!amt) { msgEl.style.color='var(--red)'; msgEl.textContent = '金額を入力してください'; return; }
    body.amount_usd = amt;
  } else {
    body.amount_usd = 0;  // SELL は全売り（サーバー側で計算）
  }

  btn.disabled = true;
  btn.textContent = '実行中...';
  msgEl.textContent = '';

  try {
    const res = await fetch('/api/manual_trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(r => r.json());

    if (res.error) {
      msgEl.style.color = 'var(--red)';
      msgEl.textContent = '❌ ' + res.error;
      btn.disabled = false;
      btn.textContent = '実行';
      return;
    }

    const sign  = res.pnl >= 0 ? '+' : '';
    const pnlTx = res.action === 'SELL' ? ` | PnL: ${sign}$${fmt(res.pnl)}` : '';
    msgEl.style.color = 'var(--green)';
    msgEl.textContent = `✓ ${res.action} ${res.coin} @ $${fmt(res.price)}${pnlTx}${res.pushed ? ' → GitHub反映済' : ''}`;

    // 3秒後にモーダルを閉じてリロード
    setTimeout(() => {
      closeTradeModal();
      loadAll();
      btn.disabled = false;
      btn.textContent = '実行';
      msgEl.textContent = '';
    }, 3000);
  } catch(e) {
    msgEl.style.color = 'var(--red)';
    msgEl.textContent = '通信エラー';
    btn.disabled = false;
    btn.textContent = '実行';
  }
}

loadAll();
setInterval(loadAll, 60000);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)


TRADE_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI HOLDINGS | トレーディングビュー</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0b0e14; --card: rgba(23,27,38,0.9); --border: rgba(255,255,255,0.08);
    --text: #fff; --muted: #94a3b8; --accent: #6366f1;
    --green: #10b981; --red: #f43f5e; --glass: rgba(255,255,255,0.03);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0b0e14; color: var(--text);
    font-family: 'Inter','Noto Sans JP',sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
  @keyframes fadeIn { from{opacity:0;transform:translateY(6px)} to{opacity:1;transform:translateY(0)} }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

  /* ── topbar ── */
  .topbar {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 20px; border-bottom: 1px solid var(--border);
    background: rgba(11,14,20,.95); backdrop-filter: blur(20px); flex-shrink: 0;
  }
  .topbar a { color: var(--muted); text-decoration: none; font-size: 13px; font-weight:600; }
  .topbar a:hover { color: var(--text); }
  .ticker-selector { display: flex; gap: 6px; flex-wrap: wrap; }
  .ticker-btn {
    padding: 6px 14px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--glass); color: var(--muted); font-size: 12px; font-weight: 700;
    cursor: pointer; transition: all .2s;
  }
  .ticker-btn:hover { border-color: var(--accent); color: var(--accent); }
  .ticker-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  .ticker-input {
    background: rgba(255,255,255,.05); border: 1px solid var(--border);
    color: var(--text); padding: 6px 12px; border-radius: 8px; font-size: 13px; width: 100px; outline: none;
  }
  .ticker-input:focus { border-color: var(--accent); }
  .interval-group { display: flex; gap: 4px; margin-left: auto; }
  .iv-btn {
    padding: 5px 11px; border-radius: 6px; border: 1px solid var(--border);
    background: var(--glass); color: var(--muted); font-size: 11px; font-weight: 700;
    cursor: pointer; transition: all .2s;
  }
  .iv-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }

  /* ── price header ── */
  .price-header {
    display: flex; align-items: baseline; gap: 14px;
    padding: 10px 20px; border-bottom: 1px solid var(--border);
    background: rgba(11,14,20,.8); flex-shrink: 0;
  }
  .price-ticker { font-size: 15px; font-weight: 800; color: var(--muted); }
  .price-value  { font-size: 32px; font-weight: 900; font-family: monospace; letter-spacing: -0.04em; }
  .price-change { font-size: 15px; font-weight: 700; }
  .live-dot { width:7px;height:7px;border-radius:50%;background:var(--green);display:inline-block;animation:pulse 2s infinite;margin-right:4px; }
  .refresh-info { font-size:11px; color:var(--muted); margin-left:auto; }

  /* ── main layout ── */
  .main { display: flex; flex: 1; overflow: hidden; }
  .chart-area { flex: 1; padding: 16px; display: flex; flex-direction: column; min-width: 0; }
  .chart-wrap { flex: 1; position: relative; }
  canvas#main-chart { width: 100% !important; height: 100% !important; }

  /* ── right panel ── */
  .side-panel {
    width: 280px; flex-shrink: 0; border-left: 1px solid var(--border);
    background: var(--card); display: flex; flex-direction: column; overflow-y: auto;
  }
  .panel-section { padding: 16px; border-bottom: 1px solid var(--border); }
  .panel-title { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing:.08em; margin-bottom: 12px; }

  /* action toggle */
  .action-row { display: flex; gap: 6px; margin-bottom: 12px; }
  .act-btn {
    flex: 1; padding: 9px; border-radius: 8px; border: 1px solid var(--border);
    background: var(--glass); color: var(--muted); font-weight: 800; font-size: 14px;
    cursor: pointer; transition: all .2s; letter-spacing:.05em;
  }
  .act-btn.buy.on   { background:rgba(16,185,129,.2); color:var(--green); border-color:rgba(16,185,129,.5); }
  .act-btn.sell.on  { background:rgba(244,63,94,.2);  color:var(--red);   border-color:rgba(244,63,94,.5); }
  .short-toggle { display:flex; align-items:center; gap:6px; margin-bottom:10px; font-size:11px; color:var(--muted); cursor:pointer; user-select:none; }
  .short-toggle input[type=checkbox] { accent-color:var(--accent); width:14px; height:14px; cursor:pointer; }
  .short-toggle.active { color:#a78bfa; }

  .form-label { font-size:11px;color:var(--muted);margin-bottom:4px;font-weight:600;display:block;text-transform:uppercase;letter-spacing:.06em; }
  .form-input {
    width:100%;background:rgba(255,255,255,.05);border:1px solid var(--border);
    color:var(--text);padding:8px 12px;border-radius:8px;font-size:14px;outline:none;margin-bottom:10px;
  }
  .form-input:focus { border-color: var(--accent); }
  select.form-input option { background: #131720; }
  .price-row2 { display:flex;gap:6px;align-items:center; }
  .price-row2 input { flex:1;margin-bottom:0; }
  .sync-btn {
    padding:8px 10px;border-radius:8px;border:1px solid var(--border);
    background:var(--glass);color:var(--muted);font-size:11px;cursor:pointer;white-space:nowrap;
    transition:all .2s;font-weight:700;
  }
  .sync-btn:hover { border-color:var(--accent);color:var(--accent); }
  .exec-btn {
    width:100%;padding:11px;border-radius:10px;border:none;
    font-size:15px;font-weight:900;cursor:pointer;transition:all .2s;letter-spacing:.05em;
  }
  .exec-btn.buy-mode  { background:var(--green); color:#fff; box-shadow:0 4px 12px rgba(16,185,129,.3); }
  .exec-btn.sell-mode { background:var(--red);   color:#fff; box-shadow:0 4px 12px rgba(244,63,94,.3); }
  .exec-btn:disabled { opacity:.4; cursor:not-allowed; }
  .result-msg { font-size:12px;margin-top:8px;text-align:center;min-height:18px; }

  /* positions */
  .pos-item { font-size:12px; padding: 8px 0; border-bottom:1px solid var(--border); }
  .pos-item:last-child { border-bottom: none; }
  .pos-ticker { font-weight:800;font-size:13px; }
  .pos-detail { color:var(--muted);font-size:11px;margin-top:2px; }

  /* recent trades */
  .trade-item { font-size:11px; padding: 7px 0; border-bottom:1px solid var(--border); display:flex;align-items:center;gap:8px; }
  .trade-item:last-child { border-bottom:none; }
  .badge { padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;border:1px solid transparent; }
  .badge-buy  { background:rgba(16,185,129,.1);color:var(--green);border-color:rgba(16,185,129,.2); }
  .badge-sell { background:rgba(244,63,94,.1); color:var(--red);  border-color:rgba(244,63,94,.2); }
</style>
</head>
<body>

<!-- topbar -->
<div class="topbar">
  <a href="/">← ダッシュボード</a>
  <span style="color:var(--border)">|</span>
  <div class="ticker-selector" id="ticker-presets">
    <button class="ticker-btn active" onclick="selectTicker('bitcoin')">BTC</button>
    <button class="ticker-btn" onclick="selectTicker('MSFT')">MSFT</button>
    <button class="ticker-btn" onclick="selectTicker('AAPL')">AAPL</button>
    <button class="ticker-btn" onclick="selectTicker('NVDA')">NVDA</button>
    <button class="ticker-btn" onclick="selectTicker('SPY')">SPY</button>
    <button class="ticker-btn" onclick="selectTicker('QQQ')">QQQ</button>
  </div>
  <input class="ticker-input" id="custom-ticker" placeholder="銘柄入力..." onkeydown="if(event.key==='Enter') selectTicker(this.value.trim())">
  <div class="interval-group">
    <button class="iv-btn" onclick="setIv('30s')">30秒</button>
    <button class="iv-btn" onclick="setIv('1m')">1分</button>
    <button class="iv-btn" onclick="setIv('5m')">5分</button>
    <button class="iv-btn" onclick="setIv('15m')">15分</button>
    <button class="iv-btn active" onclick="setIv('1h')">1時間</button>
    <button class="iv-btn" onclick="setIv('1d')">日足</button>
  </div>
</div>

<!-- price header -->
<div class="price-header">
  <span class="price-ticker" id="ph-ticker">BTC</span>
  <span class="price-value" id="ph-price">--</span>
  <span class="price-change" id="ph-change"></span>
  <span style="display:inline-flex;align-items:center;font-size:12px;color:var(--muted)">
    <span class="live-dot"></span>LIVE
  </span>
  <span class="refresh-info" id="refresh-info">次の更新まで --s</span>
</div>

<!-- main -->
<div class="main">
  <!-- chart -->
  <div class="chart-area">
    <div class="chart-wrap">
      <canvas id="main-chart"></canvas>
    </div>
  </div>

  <!-- right panel -->
  <div class="side-panel">

    <!-- trade form -->
    <div class="panel-section">
      <div class="panel-title">売買パネル</div>
      <div class="action-row">
        <button class="act-btn buy on" id="act-buy"  onclick="setAct('BUY')">BUY</button>
        <button class="act-btn sell"   id="act-sell" onclick="setAct('SELL')">SELL</button>
      </div>
      <label class="short-toggle" id="short-toggle-label" onclick="toggleShortMode()">
        <input type="checkbox" id="short-mode-cb" onclick="event.stopPropagation();toggleShortMode()">
        空売りモード（SELL=売り建て / BUY=買戻し）
      </label>

      <label class="form-label">ポートフォリオ</label>
      <select class="form-input" id="f-bot">
        <option value="SHORT">短期 (SHORT)</option>
        <option value="MEDIUM">中期 (MEDIUM)</option>
        <option value="LONG">長期 (LONG)</option>
        <option value="MACRO">マクロ (MACRO)</option>
      </select>

      <label class="form-label">価格 (USD)</label>
      <div class="price-row2" style="margin-bottom:10px;">
        <input class="form-input" id="f-price" type="number" step="0.01" placeholder="0.00">
        <button class="sync-btn" onclick="syncPrice()" title="チャートの現在価格を入力">↑ 同期</button>
      </div>

      <div id="f-buy-block">
        <label class="form-label">金額 (USD)</label>
        <input class="form-input" id="f-amount" type="number" step="1" placeholder="投資額">
      </div>

      <div id="f-sell-block" style="display:none;font-size:12px;color:var(--muted);padding:8px 0;">
        銘柄を選択しているポートフォリオの保有全量を売却します
      </div>

      <label class="form-label">メモ</label>
      <input class="form-input" id="f-note" type="text" placeholder="手動売買">

      <button class="exec-btn buy-mode" id="exec-btn" onclick="execTrade()">BUY 実行</button>
      <div class="result-msg" id="result-msg"></div>
    </div>

    <!-- positions -->
    <div class="panel-section">
      <div class="panel-title">保有ポジション</div>
      <div id="pos-list"><span style="font-size:12px;color:var(--muted)">読み込み中...</span></div>
    </div>

    <!-- recent trades -->
    <div class="panel-section">
      <div class="panel-title">直近トレード</div>
      <div id="trade-list"><span style="font-size:12px;color:var(--muted)">読み込み中...</span></div>
    </div>

  </div>
</div>

<script>
let currentTicker = 'bitcoin';
let currentIv     = '1h';
let currentAct    = 'BUY';
let mainChart     = null;
let chartData     = { labels: [], prices: [] };
let latestPrice   = null;
let prevPrice     = null;
let refreshTimer  = null;
let countdown     = 30;

const REFRESH_SEC = 30;

function fmt(n, d=2) {
  if (n==null||isNaN(n)) return '--';
  return Number(n).toLocaleString('ja-JP',{minimumFractionDigits:d,maximumFractionDigits:d});
}

// ── マーカー画像生成（キャッシュ付き）────────────────────
const _mk2 = {};
function markerImg2(shape, fill, brd, sz=20) {
  const k=`${shape}|${fill}|${brd}`;
  if(_mk2[k]) return _mk2[k];
  const cv=document.createElement('canvas'); cv.width=cv.height=sz;
  const g=cv.getContext('2d'), m=1.5;
  if(shape==='up'||shape==='dn') {
    g.beginPath();
    if(shape==='up'){g.moveTo(sz/2,m);g.lineTo(sz-m,sz-m);g.lineTo(m,sz-m);}
    else            {g.moveTo(sz/2,sz-m);g.lineTo(sz-m,m);g.lineTo(m,m);}
    g.closePath(); g.fillStyle=fill; g.fill(); g.strokeStyle=brd; g.lineWidth=2; g.stroke();
  } else {
    const ch={star:'★',club:'♣'}[shape]||'●';
    g.font=`bold ${sz+2}px serif`; g.textAlign='center'; g.textBaseline='middle';
    g.fillStyle=brd; g.fillText(ch,sz/2+0.8,sz/2+0.8);
    g.fillStyle=fill; g.fillText(ch,sz/2,sz/2);
  }
  const img=new Image(); img.src=cv.toDataURL(); _mk2[k]=img; return img;
}
function tradeMarker2(t) {
  const f={SHORT:'#60a5fa',MEDIUM:'#10b981',LONG:'#fb923c',MACRO:'#f472b6'}[t.bot_type]||'#6366f1';
  const b=t.is_manual?'#f43f5e':'#ffffff';
  const s=t.action==='BUY'?(t.is_short?'dn':'up'):(t.pnl>=0?(t.is_short?'club':'star'):'dn');
  return markerImg2(s,f,b);
}

function toJST(s) {
  if (!s) return '';
  try {
    return new Date(s).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})+' JST';
  } catch(e){return s.substring(5,16);}
}

// ── ticker / interval ────────────────────────────────
function selectTicker(t) {
  if (!t) return;
  // bitcoinは小文字、それ以外は大文字
  currentTicker = t.toLowerCase()==='btc' ? 'bitcoin' : t;
  document.getElementById('ph-ticker').textContent = currentTicker.toUpperCase().replace('BITCOIN','BTC');
  document.querySelectorAll('.ticker-btn').forEach(b => {
    const v = b.getAttribute('onclick').match(/'([^']+)'/)?.[1] || '';
    b.classList.toggle('active', v===currentTicker);
  });
  document.getElementById('custom-ticker').value = '';
  document.getElementById('f-price').value = '';  // ティッカー変更時は価格をリセット→自動同期
  latestPrice = null;
  loadChart();
  loadSide();
}

function setIv(iv) {
  currentIv = iv;
  document.querySelectorAll('.iv-btn').forEach(b => {
    b.classList.toggle('active', b.getAttribute('onclick').includes(`'${iv}'`));
  });
  loadChart();
}

// ── chart ─────────────────────────────────────────────
async function loadChart() {
  try {
    const res = await fetch(`/api/history/${encodeURIComponent(currentTicker)}?interval=${currentIv}`).then(r=>r.json());
    const candles = res.candles || [];
    if (!candles.length) return;

    chartData.labels = candles.map(c=>c.date);
    chartData.prices = candles.map(c=>c.price);

    prevPrice   = latestPrice;
    latestPrice = chartData.prices[chartData.prices.length-1];
    updatePriceHeader();

    // build trade markers
    const ptRadius = chartData.prices.map(()=>0);
    const ptStyle  = chartData.prices.map(()=>false);
    const tradeByIdx = {};
    (res.trades||[]).forEach(t=>{
      let idx = chartData.labels.indexOf(t.timestamp);
      if (idx<0) {
        for (let i=chartData.labels.length-1;i>=0;i--) {
          if (chartData.labels[i]<=t.timestamp){idx=i;break;}
        }
      }
      if (idx>=0) {
        ptRadius[idx] = 10;
        ptStyle[idx]  = tradeMarker2(t);
        tradeByIdx[idx] = t;
      }
    });

    const isBull = chartData.prices[0] <= latestPrice;
    const lineColor = isBull ? 'rgba(16,185,129,1)' : 'rgba(244,63,94,1)';
    const fillColor = isBull ? 'rgba(16,185,129,0.07)' : 'rgba(244,63,94,0.07)';

    // tradesList: sorted array used by onHover to find BUY/SELL pairs
    const tradesList = (res.trades||[]).map(t => {
      let idx = chartData.labels.indexOf(t.timestamp);
      if (idx<0) {
        for (let i=chartData.labels.length-1;i>=0;i--) {
          if (chartData.labels[i]<=t.timestamp){idx=i;break;}
        }
      }
      return {...t, _idx: idx};
    }).filter(t => t._idx >= 0).sort((a,b)=>a._idx-b._idx);

    function setFillRange(buyIdx, sellIdx, profit) {
      const nullArr = chartData.prices.map(()=>null);
      const endIdx  = sellIdx >= 0 ? sellIdx : chartData.prices.length - 1;
      const color   = profit ? 'rgba(16,185,129,0.22)' : 'rgba(244,63,94,0.22)';
      for (let i = buyIdx; i <= endIdx; i++) nullArr[i] = chartData.prices[i];
      mainChart.data.datasets[1].data = nullArr;
      mainChart.data.datasets[1].backgroundColor = color;
      mainChart.update('none');
    }
    function clearFill() {
      if (!mainChart) return;
      mainChart.data.datasets[1].data = chartData.prices.map(()=>null);
      mainChart.update('none');
    }

    if (mainChart) {
      mainChart.data.labels = chartData.labels;
      mainChart.data.datasets[0].data             = chartData.prices;
      mainChart.data.datasets[0].borderColor      = lineColor;
      mainChart.data.datasets[0].backgroundColor  = fillColor;
      mainChart.data.datasets[0].pointRadius      = ptRadius;
      mainChart.data.datasets[0].pointStyle       = ptStyle;
      mainChart.data.datasets[1].data             = chartData.prices.map(()=>null);
      mainChart._tradeByIdx = tradeByIdx;
      mainChart._tradesList = tradesList;
      mainChart.update('none');
    } else {
      const ctx = document.getElementById('main-chart').getContext('2d');
      mainChart = new Chart(ctx, {
        type:'line',
        data:{
          labels: chartData.labels,
          datasets:[
            {
              data: chartData.prices,
              borderColor: lineColor, borderWidth:2,
              backgroundColor: fillColor, fill:true, tension:0.2,
              pointRadius: ptRadius, pointHoverRadius: ptRadius.map(r=>r>0?r+4:0),
              pointHitRadius: ptRadius.map(r=>r>0?14:0),
              pointStyle: ptStyle,
            },
            {
              // hover fill highlight (BUY→SELL range)
              data: chartData.prices.map(()=>null),
              borderColor: 'transparent', borderWidth:0,
              backgroundColor: 'rgba(16,185,129,0.22)',
              fill: 'origin', tension:0.2,
              pointRadius: 0, pointHoverRadius: 0, pointHitRadius: 0,
              spanGaps: false,
            }
          ]
        },
        options:{
          responsive:true, maintainAspectRatio:false,
          animation:{duration:200},
          interaction:{mode:'nearest', intersect:true},
          onHover: (event, elements) => {
            if (!mainChart) return;
            if (!elements.length) { clearFill(); return; }
            const idx = elements[0].index;
            if (elements[0].datasetIndex !== 0) return;
            const t = (mainChart._tradeByIdx||{})[idx];
            if (!t) { clearFill(); return; }
            const trades = mainChart._tradesList || [];
            if (t.action === 'BUY') {
              // find next SELL by bot_type after this index
              const sell = trades.find(x => x._idx > idx && x.action === 'SELL' && x.bot_type === t.bot_type);
              const sellIdx = sell ? sell._idx : -1;
              const curPrice = chartData.prices[chartData.prices.length-1];
              const profit = sell ? sell.pnl >= 0 : curPrice > t.price;
              setFillRange(idx, sellIdx, profit);
            } else {
              // SELL: find the most recent BUY before this index
              const buy = [...trades].reverse().find(x => x._idx < idx && x.action === 'BUY' && x.bot_type === t.bot_type);
              const buyIdx = buy ? buy._idx : idx;
              const profit = t.pnl >= 0;
              setFillRange(buyIdx, idx, profit);
            }
          },
          plugins:{
            legend:{display:false},
            tooltip:{
              backgroundColor:'rgba(0,0,0,0.85)',
              filter: item => item.datasetIndex === 0,
              callbacks:{
                title: items => {
                  const t = (mainChart._tradeByIdx||{})[items[0].dataIndex];
                  return t ? `${t.action==='BUY'?'▲ BUY':'▼ SELL'}  ${items[0].label}` : items[0].label;
                },
                label: ctx => {
                  const t = (mainChart._tradeByIdx||{})[ctx.dataIndex];
                  if (!t) return `$${fmt(ctx.parsed.y)}`;
                  const lines = [
                    `価格: $${fmt(ctx.parsed.y)}`,
                    `株数: ${fmt(t.amount,4)}`,
                    `約定額: $${fmt(t.value_usd)}`,
                  ];
                  if (t.action==='SELL') lines.push(`確定損益: ${t.pnl>=0?'+':''}$${fmt(t.pnl)}`);
                  return lines;
                }
              }
            }
          },
          scales:{
            x:{
              ticks:{color:'#475569', maxTicksLimit:8, font:{size:10}},
              grid:{color:'rgba(255,255,255,0.03)'}
            },
            y:{
              position:'right',
              ticks:{color:'#475569', font:{size:11},
                callback: v => '$'+Number(v).toLocaleString()},
              grid:{color:'rgba(255,255,255,0.04)'}
            }
          }
        }
      });
      mainChart._tradeByIdx = tradeByIdx;
      mainChart._tradesList = tradesList;
    }
  } catch(e){ console.error(e); }
}

function updatePriceHeader() {
  if (latestPrice==null) return;
  const el = document.getElementById('ph-price');
  el.textContent = '$'+fmt(latestPrice);
  const chEl = document.getElementById('ph-change');
  if (prevPrice && prevPrice!==latestPrice) {
    const d = latestPrice-prevPrice;
    const p = (d/prevPrice)*100;
    chEl.textContent = (d>=0?'+':'')+fmt(d)+' ('+(d>=0?'+':'')+fmt(p)+'%)';
    chEl.style.color = d>=0 ? 'var(--green)' : 'var(--red)';
  }
  // 価格フィールドが空なら自動同期（ティッカー変更直後 or 未入力時）
  const priceEl = document.getElementById('f-price');
  if (!priceEl.value) priceEl.value = latestPrice.toFixed(2);
}

// ── auto refresh ──────────────────────────────────────
function startRefreshTimer() {
  clearInterval(refreshTimer);
  countdown = REFRESH_SEC;
  refreshTimer = setInterval(()=>{
    countdown--;
    document.getElementById('refresh-info').textContent = `次の更新まで ${countdown}s`;
    if (countdown <= 0) {
      loadChart();
      loadSide();
      countdown = REFRESH_SEC;
    }
  }, 1000);
}

// ── side panel ────────────────────────────────────────
async function loadSide() {
  // positions
  try {
    const s = await fetch('/api/summary_local').then(r=>r.json());
    const portfolios = s.portfolios || {};
    let html = '';
    let any = false;
    for (const [bk, pd] of Object.entries(portfolios)) {
      const bLabel = {SHORT:'短期',MEDIUM:'中期',LONG:'長期',MACRO:'マクロ',ATTACK:'攻撃型',VOLT:'ボラ型'}[bk]||bk;
      // ロングポジション
      for (const [tk, p] of Object.entries(pd.positions||{})) {
        any = true;
        const lp = latestPrice && tk.toUpperCase()===currentTicker.toUpperCase() ? latestPrice : p.buy_price;
        const prof = (lp-p.buy_price)*p.shares;
        const pct  = (lp/p.buy_price-1)*100;
        const c    = prof>=0?'var(--green)':'var(--red)';
        html += `<div class="pos-item">
          <div style="display:flex;justify-content:space-between;">
            <span class="pos-ticker">${tk} <span style="font-size:10px;color:var(--muted)">${bLabel}</span></span>
            <span style="color:${c};font-weight:700;font-size:12px;">${prof>=0?'+':''}$${fmt(prof)} (${pct>=0?'+':''}${fmt(pct)}%)</span>
          </div>
          <div class="pos-detail">取得 $${fmt(p.buy_price)} × ${fmt(p.shares,4)}株 = $${fmt(p.cost_basis)}</div>
        </div>`;
      }
      // 空売りポジション
      for (const [tk, p] of Object.entries(pd.short_positions||{})) {
        any = true;
        const lp = latestPrice && tk.toUpperCase()===currentTicker.toUpperCase() ? latestPrice : p.buy_price;
        const prof = (p.buy_price-lp)*p.shares;  // 空売りは逆
        const pct  = (p.buy_price/lp-1)*100;
        const c    = prof>=0?'var(--green)':'var(--red)';
        html += `<div class="pos-item" style="border-left:2px solid #a78bfa;padding-left:6px;">
          <div style="display:flex;justify-content:space-between;">
            <span class="pos-ticker">${tk} <span style="font-size:10px;color:#a78bfa">空売り・${bLabel}</span></span>
            <span style="color:${c};font-weight:700;font-size:12px;">${prof>=0?'+':''}$${fmt(prof)} (${pct>=0?'+':''}${fmt(pct)}%)</span>
          </div>
          <div class="pos-detail">建値 $${fmt(p.buy_price)} × ${fmt(p.shares,4)}株 = $${fmt(p.cost_basis)}</div>
        </div>`;
      }
    }
    document.getElementById('pos-list').innerHTML = any ? html : '<span style="font-size:12px;color:var(--muted)">保有なし</span>';
  } catch(e){}

  // recent trades
  try {
    const trades = await fetch('/api/trades').then(r=>r.json());
    const filtered = trades.filter(t=>t.action==='BUY'||t.action==='SELL').slice(0,12);
    document.getElementById('trade-list').innerHTML = filtered.map(t=>`
      <div class="trade-item">
        <span class="badge badge-${t.action.toLowerCase()}">${t.action==='BUY'?'買':'売'}</span>
        <span style="font-weight:700">${t.coin}</span>
        <span style="color:var(--muted);font-size:10px;flex:1">$${fmt(t.price)}</span>
        <span style="font-size:10px;color:var(--muted)">${(t.timestamp_jst||'').replace(' JST','')}</span>
      </div>`).join('') || '<span style="font-size:12px;color:var(--muted)">履歴なし</span>';
  } catch(e){}
}

// ── trade form ────────────────────────────────────────
let isShortMode = false;

function toggleShortMode() {
  isShortMode = !isShortMode;
  document.getElementById('short-mode-cb').checked = isShortMode;
  const label = document.getElementById('short-toggle-label');
  label.classList.toggle('active', isShortMode);
  updateExecBtn();
}

function updateExecBtn() {
  const btn = document.getElementById('exec-btn');
  if (isShortMode) {
    if (currentAct === 'SELL') {
      btn.className = 'exec-btn sell-mode';
      btn.textContent = '空売り建て 実行';
    } else {
      btn.className = 'exec-btn buy-mode';
      btn.textContent = '買戻し（カバー）実行';
    }
  } else {
    btn.className = `exec-btn ${currentAct==='BUY'?'buy-mode':'sell-mode'}`;
    btn.textContent = currentAct==='BUY' ? 'BUY 実行' : 'SELL 実行';
  }
}

function setAct(a) {
  currentAct = a;
  document.getElementById('act-buy').classList.toggle('on', a==='BUY');
  document.getElementById('act-sell').classList.toggle('on', a==='SELL');
  document.getElementById('f-buy-block').style.display  = a==='BUY'  ? '' : 'none';
  document.getElementById('f-sell-block').style.display = a==='SELL' ? '' : 'none';
  updateExecBtn();
}

function syncPrice() {
  if (latestPrice) document.getElementById('f-price').value = latestPrice.toFixed(2);
}

async function execTrade() {
  const coin    = currentTicker;
  const botType = document.getElementById('f-bot').value;
  const price   = parseFloat(document.getElementById('f-price').value||'0');
  const note    = document.getElementById('f-note').value || (isShortMode ? '空売り' : '手動売買');
  const msgEl   = document.getElementById('result-msg');
  const btn     = document.getElementById('exec-btn');

  if (!price) { msgEl.style.color='var(--red)'; msgEl.textContent='価格を入力'; return; }

  let body = {action:currentAct, coin, bot_type:botType, price, note, amount_usd:0};

  if (isShortMode && currentAct==='SELL') {
    // 空売り建て
    const amt = parseFloat(document.getElementById('f-amount').value||'0');
    if (!amt) { msgEl.style.color='var(--red)'; msgEl.textContent='証拠金（金額）を入力'; return; }
    body.amount_usd = amt;
    body.is_short_sell = true;
  } else if (isShortMode && currentAct==='BUY') {
    // 買戻し（カバー）: amount_usd不要、サーバー側で計算
    body.amount_usd = 0;
  } else if (currentAct==='BUY') {
    const amt = parseFloat(document.getElementById('f-amount').value||'0');
    if (!amt) { msgEl.style.color='var(--red)'; msgEl.textContent='金額を入力'; return; }
    body.amount_usd = amt;
  }

  btn.disabled = true;
  msgEl.style.color='var(--muted)'; msgEl.textContent='実行中...';
  try {
    const res = await fetch('/api/manual_trade',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
    if (res.error) {
      msgEl.style.color='var(--red)'; msgEl.textContent='❌ '+res.error;
    } else {
      const pnlTx = res.pnl ? ` PnL: ${res.pnl>=0?'+':''}$${fmt(res.pnl)}` : '';
      const shortTx = res.is_short ? ' [空売り]' : '';
      msgEl.style.color='var(--green)'; msgEl.textContent=`✓ ${res.action}${shortTx} @ $${fmt(res.price)}${pnlTx}`;
      document.getElementById('f-amount').value = '';
      loadSide();
    }
  } catch(e){ msgEl.style.color='var(--red)'; msgEl.textContent='通信エラー'; }
  btn.disabled = false;
}

// ── init ──────────────────────────────────────────────
loadChart();
loadSide();
startRefreshTimer();
</script>
</body>
</html>"""


@app.route("/trade")
def trade_view():
    return render_template_string(TRADE_HTML)


if __name__ == "__main__":
    print("[DASHBOARD] http://localhost:5000 で起動します")
    app.run(host="0.0.0.0", port=5000, debug=False)
