"""
SCALP bot — BTC 5分足スキャルピング（自己改善型）
戦略パラメータは scalp_strategy.json を読む（日次AIが自動書き換え）
"""
import json
import numpy as np
import pandas as pd
import yfinance as yf
import warnings
from pathlib import Path
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

DATA_DIR       = Path(__file__).parent.parent / "data"
STRATEGY_FILE  = DATA_DIR / "scalp_strategy.json"
PORTFOLIO_FILE = DATA_DIR / "portfolio_scalp.json"
TRADES_FILE    = DATA_DIR / "scalp_trades.json"

TICKER          = "BTC-USD"
INITIAL_BALANCE = 10_000.0
FEE_RATE        = 0.001
SLIP_RATE       = 0.0003

DEFAULT_STRATEGY = {
    "version": 1,
    "rsi_period": 14,
    "rsi_oversold": 35,
    "rsi_overbought": 65,
    "bb_period": 20,
    "bb_std": 2.0,
    "stop_loss_pct": 0.008,
    "take_profit_pct": 0.015,
    "invest_pct": 0.80,
    "max_hold_minutes": 120,
    "require_bb": True,
    "require_rsi": True,
    "require_volume_spike": False,
}


def load_strategy() -> dict:
    if STRATEGY_FILE.exists():
        try:
            return json.loads(STRATEGY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_STRATEGY.copy()


def load_portfolio() -> dict:
    if PORTFOLIO_FILE.exists():
        try:
            return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "balance": INITIAL_BALANCE,
        "initial_balance": INITIAL_BALANCE,
        "position": None,
        "trade_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "total_realized_pnl": 0.0,
        "last_updated": None,
    }


def save_portfolio(p: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PORTFOLIO_FILE.write_text(json.dumps(p, indent=2, ensure_ascii=False), encoding="utf-8")


def append_trade(trade: dict):
    trades = []
    if TRADES_FILE.exists():
        try:
            trades = json.loads(TRADES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    trades.append(trade)
    TRADES_FILE.write_text(json.dumps(trades, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_candles() -> pd.DataFrame | None:
    try:
        df = yf.download(TICKER, period="1d", interval="5m", progress=False, auto_adjust=True)
        if df.empty or len(df) < 30:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception as e:
        print(f"  [ERROR] データ取得失敗: {e}")
        return None


def calc_indicators(df: pd.DataFrame, s: dict) -> dict:
    close  = df["Close"].squeeze()
    volume = df["Volume"].squeeze()

    # RSI
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(s["rsi_period"]).mean()
    loss  = (-delta.clip(upper=0)).rolling(s["rsi_period"]).mean()
    rsi   = float((100 - 100 / (1 + gain / (loss + 1e-9))).iloc[-1])

    # Bollinger Bands
    ma       = close.rolling(s["bb_period"]).mean()
    std      = close.rolling(s["bb_period"]).std()
    bb_upper = float((ma + s["bb_std"] * std).iloc[-1])
    bb_lower = float((ma - s["bb_std"] * std).iloc[-1])

    # Volume spike vs 20-bar avg
    vol_spike = float(volume.iloc[-1]) > float(volume.rolling(20).mean().iloc[-1]) * 1.5

    return {
        "price":     float(close.iloc[-1]),
        "rsi":       rsi,
        "bb_upper":  bb_upper,
        "bb_lower":  bb_lower,
        "vol_spike": vol_spike,
    }


def run_cycle():
    now = datetime.now(timezone.utc)
    s   = load_strategy()
    p   = load_portfolio()

    print(f"\n{'='*50}")
    print(f"[SCALP v{s.get('version',1)}] {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  残高: ${p['balance']:,.2f}  PnL累計: ${p.get('total_realized_pnl',0):+,.2f}")

    df = fetch_candles()
    if df is None:
        p["last_updated"] = now.isoformat()
        save_portfolio(p)
        return

    ind   = calc_indicators(df, s)
    price = ind["price"]
    print(f"  BTC: ${price:,.0f}  RSI={ind['rsi']:.1f}  BB下限=${ind['bb_lower']:,.0f}")

    # ── EXIT ──────────────────────────────────────────────────
    pos = p.get("position")
    if pos:
        entry      = pos["price"]
        shares     = pos["shares"]
        cost       = pos["cost"]
        entry_time = datetime.fromisoformat(pos["entry_time"])
        hold_min   = (now - entry_time).total_seconds() / 60
        change_pct = (price - entry) / entry

        sl_hit   = change_pct <= -s["stop_loss_pct"]
        tp_hit   = change_pct >= s["take_profit_pct"]
        time_out = hold_min  >= s["max_hold_minutes"]

        print(f"  保有中: entry=${entry:,.0f}  変動={change_pct*100:+.2f}%  {hold_min:.0f}分経過")

        if sl_hit or tp_hit or time_out:
            reason     = "SL" if sl_hit else ("TP" if tp_hit else "timeout")
            sell_price = price * (1 - SLIP_RATE)
            proceeds   = shares * sell_price
            fee        = proceeds * FEE_RATE
            pnl        = proceeds - fee - cost

            p["balance"]           += proceeds - fee
            p["position"]           = None
            p["trade_count"]        = p.get("trade_count", 0) + 1
            p["total_realized_pnl"] = p.get("total_realized_pnl", 0.0) + pnl
            if pnl >= 0:
                p["win_count"] = p.get("win_count", 0) + 1
            else:
                p["loss_count"] = p.get("loss_count", 0) + 1

            sign = "+" if pnl >= 0 else ""
            print(f"\n  [SELL] {reason}  ${sell_price:,.0f}  PnL={sign}${pnl:,.2f}  残高=${p['balance']:,.2f}")

            append_trade({
                "id":               p["trade_count"],
                "entry_time":       pos["entry_time"],
                "exit_time":        now.isoformat(),
                "entry_price":      round(entry, 2),
                "exit_price":       round(sell_price, 2),
                "shares":           shares,
                "pnl":              round(pnl, 4),
                "pnl_pct":          round(change_pct * 100, 3),
                "reason":           reason,
                "hold_min":         round(hold_min, 1),
                "rsi_at_entry":     pos.get("rsi_at_entry"),
                "strategy_version": s.get("version", 1),
            })
            p["last_updated"] = now.isoformat()
            save_portfolio(p)
            return

        print("  → HOLD")
        p["last_updated"] = now.isoformat()
        save_portfolio(p)
        return

    # ── ENTRY ─────────────────────────────────────────────────
    ok = True
    if s.get("require_rsi", True):
        ok = ok and (ind["rsi"] < s["rsi_oversold"])
    if s.get("require_bb", True):
        ok = ok and (price < ind["bb_lower"])
    if s.get("require_volume_spike", False):
        ok = ok and ind["vol_spike"]

    if ok:
        invest    = p["balance"] * s["invest_pct"]
        buy_price = price * (1 + SLIP_RATE)
        fee       = invest * FEE_RATE
        shares    = (invest - fee) / buy_price
        p["balance"]  -= invest
        p["position"]  = {
            "ticker":       TICKER,
            "price":        buy_price,
            "shares":       shares,
            "cost":         invest,
            "entry_time":   now.isoformat(),
            "rsi_at_entry": ind["rsi"],
        }
        print(f"\n  [BUY] ${buy_price:,.0f}  {shares:.6f}BTC  投資=${invest:,.0f}")
    else:
        print(f"  → シグナルなし (RSI={ind['rsi']:.1f} BB_ok={price < ind['bb_lower']})")

    p["last_updated"] = now.isoformat()
    save_portfolio(p)


if __name__ == "__main__":
    run_cycle()
