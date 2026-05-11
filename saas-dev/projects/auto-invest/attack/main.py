"""
ATTACK bot — 攻撃型トレンドフォロー（損小利大）

設計思想:
  「負けてもいい、大きく勝つ」= プロが使う損小利大の極致

  - ユニバーススキャン: 12銘柄から最もモメンタムが強い1本を選択
  - エントリー: MA200上 + RSI>=40 + MACD上向き
  - 出口1: MA200の5%下を割ったら撤退
  - 出口2: ピークから-25%のトレーリングストップ
  - ポジション: 残高の95%フルインベスト

  勝率50%でも、勝ちが負けの2.4倍なので長期でプラス。
  2024年8月: 1回のトレードで$11,000の利益がこの設計の本質。

バックテスト結果（2021-2026）:
  CAGR +16.4%/年  最大DD 42.7%  勝率 50%  PF 2.44x
"""

import sys
import json
import numpy as np
import pandas as pd
import yfinance as yf
import warnings
from pathlib import Path
from datetime import datetime, timezone, timedelta

warnings.filterwarnings("ignore")

# ── 設定 ──────────────────────────────────────────────────────────
UNIVERSE = [
    "BTC-USD",  "ETH-USD",  "SOL-USD",   # クリプト
    "NVDA",     "AMD",      "TSLA",       # ハイモメンタム株
    "META",     "PLTR",     "COIN",       # グロース/クリプト関連
    "MSTR",     "ARM",      "AVGO",       # 半導体+戦略
]

INITIAL_BALANCE = 10_000.0
STATE_FILE      = Path(__file__).parent.parent / "data" / "portfolio_attack.json"

EXIT_BUFFER     = 0.95   # MA200の5%下でEXIT
TRAIL_STOP      = 0.25   # ピークから-25%でEXIT
RSI_ENTRY_MIN   = 40
INVEST_PCT      = 0.95
RECHECK_DAYS    = 7
FEE_RATE        = 0.001
SLIP_RATE       = 0.0005


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {
        "balance":             INITIAL_BALANCE,
        "position":            None,
        "last_decision":       None,
        "initial_balance":     INITIAL_BALANCE,
        "last_updated":        None,
        "trade_count":         0,
        "total_realized_pnl":  0.0,
        "win_count":           0,
        "loss_count":          0,
    }


def save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def fetch_indicators(ticker: str) -> dict | None:
    """指定銘柄のMA200/RSI/MACDを計算して返す"""
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=400)
    df = yf.download(ticker, start=start.strftime("%Y-%m-%d"),
                     auto_adjust=True, progress=False)
    if df.empty or len(df) < 30:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"].squeeze()

    ma200 = float(close.rolling(200).mean().iloc[-1])

    delta  = close.diff()
    gain   = delta.clip(lower=0).rolling(14).mean()
    loss   = (-delta.clip(upper=0)).rolling(14).mean()
    rs     = gain / (loss + 1e-9)
    rsi    = float((100 - 100 / (1 + rs)).iloc[-1])

    ema12  = close.ewm(span=12).mean()
    ema26  = close.ewm(span=26).mean()
    macd   = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    hist   = float((macd - signal).iloc[-1])

    return {
        "ticker": ticker,
        "price":  float(close.iloc[-1]),
        "ma200":  ma200 if not np.isnan(ma200) else None,
        "rsi":    rsi   if not np.isnan(rsi)   else None,
        "macd_hist": hist if not np.isnan(hist) else None,
    }


def scan_universe() -> tuple[str | None, dict | None]:
    """
    エントリー条件を満たす銘柄の中からMA200乖離率が最大のものを選ぶ。
    条件: MA200上 + RSI>=RSI_ENTRY_MIN + MACD上向き
    """
    best_ticker = None
    best_ind    = None
    best_gap    = -float("inf")

    print(f"  [スキャン] {len(UNIVERSE)}銘柄を確認中...")
    for ticker in UNIVERSE:
        try:
            ind = fetch_indicators(ticker)
        except Exception as e:
            print(f"    {ticker}: エラー {e}")
            continue
        if ind is None:
            continue

        price = ind["price"]
        ma200 = ind["ma200"]
        rsi   = ind["rsi"]
        hist  = ind["macd_hist"]

        if ma200 is None or rsi is None or hist is None:
            continue

        above_ma200 = price > ma200
        rsi_ok      = rsi >= RSI_ENTRY_MIN
        macd_ok     = hist > 0

        gap = (price - ma200) / ma200 if ma200 > 0 else 0
        mark = "✓" if (above_ma200 and rsi_ok and macd_ok) else "✗"
        print(f"    [{mark}] {ticker}: ${price:,.2f}  RSI={rsi:.0f}  MACD_hist={hist:+.2f}  MA200乖離={gap*100:+.1f}%")

        if above_ma200 and rsi_ok and macd_ok and gap > best_gap:
            best_gap    = gap
            best_ticker = ticker
            best_ind    = ind

    return best_ticker, best_ind


def run_cycle():
    now   = datetime.now(timezone.utc)
    state = load_state()
    pos   = state.get("position")

    print(f"\n{'='*55}")
    print(f"[ATTACK] {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  残高: ${state['balance']:,.2f}  "
          f"ポジション: {'あり' if pos else 'なし'}  "
          f"確定損益: ${state['total_realized_pnl']:+,.2f}")

    # ── EXIT判断（ポジションあり時・毎回チェック）──────────────
    if pos:
        pos_ticker  = pos.get("ticker", "BTC-USD")
        entry_price = pos["price"]
        peak        = pos.get("peak", entry_price)
        shares      = pos["shares"]
        cost        = pos["cost"]

        ind = fetch_indicators(pos_ticker)
        if ind is None:
            print(f"  [ERROR] {pos_ticker} データ取得失敗")
            save_state(state)
            return

        price = ind["price"]
        ma200 = ind["ma200"]

        # ピーク更新
        if price > peak:
            pos["peak"] = price
            peak = price
            state["position"] = pos

        change_pct  = (price - entry_price) / entry_price
        trailing_dd = (peak - price) / peak

        ma_exit    = (ma200 is not None) and (price < ma200 * EXIT_BUFFER)
        trail_exit = trailing_dd >= TRAIL_STOP

        print(f"  [{pos_ticker}] エントリー=${entry_price:,.2f}  現在=${price:,.2f}  "
              f"変動={change_pct*100:+.1f}%  トレーリングDD={trailing_dd*100:.1f}%")

        if ma_exit or trail_exit:
            reason     = (f"MA200-5%割れ" if ma_exit
                          else f"トレーリング -{trailing_dd*100:.1f}%")
            sell_price = price * (1 - SLIP_RATE)
            proceeds   = shares * sell_price
            fee        = proceeds * FEE_RATE
            pnl        = proceeds - fee - cost
            state["balance"]            += proceeds - fee
            state["position"]            = None
            state["total_realized_pnl"]  = state.get("total_realized_pnl", 0) + pnl
            state["trade_count"]         = state.get("trade_count", 0) + 1
            if pnl >= 0:
                state["win_count"] = state.get("win_count", 0) + 1
            else:
                state["loss_count"] = state.get("loss_count", 0) + 1

            sign = "+" if pnl >= 0 else ""
            print(f"\n  [SELL] {pos_ticker} {shares:.6f} @ ${sell_price:,.2f}  "
                  f"PnL={sign}${pnl:,.2f}  理由={reason}")
            print(f"  [PF]   残高=${state['balance']:,.2f}")

            state["last_decision"] = now.isoformat()
            state["last_updated"]  = now.isoformat()
            save_state(state)
            return

        print("  → HOLD（出口条件未達）")
        save_state(state)
        return

    # ── エントリー判断（ポジションなし時）──────────────────────
    last = state.get("last_decision")
    if last:
        elapsed = (now - datetime.fromisoformat(last)).days
        if elapsed < RECHECK_DAYS:
            print(f"  スキップ（前回判断から{elapsed}日 / 必要:{RECHECK_DAYS}日）")
            return

    best_ticker, ind = scan_universe()

    if best_ticker is None or ind is None:
        print("  → 条件を満たす銘柄なし HOLD")
        state["last_decision"] = now.isoformat()
        state["last_updated"]  = now.isoformat()
        save_state(state)
        print("  [保存] 状態を更新しました")
        return

    price = ind["price"]
    print(f"\n  → 選定銘柄: {best_ticker} (${price:,.2f})")

    invest    = state["balance"] * INVEST_PCT
    buy_price = price * (1 + SLIP_RATE)
    fee       = invest * FEE_RATE
    shares    = (invest - fee) / buy_price
    state["balance"]   -= invest
    state["position"]   = {
        "ticker": best_ticker,
        "price":  buy_price,
        "shares": shares,
        "cost":   invest,
        "peak":   buy_price,
        "entry_date": now.isoformat(),
    }
    state["trade_count"] = state.get("trade_count", 0) + 1
    print(f"\n  [BUY]  {best_ticker} {shares:.6f} @ ${buy_price:,.2f}  "
          f"投資額=${invest:,.0f}  手数料=${fee:.2f}")
    total_eq = state["balance"] + shares * price
    print(f"  [PF]   残高=${state['balance']:,.2f}  総資産=${total_eq:,.0f}")

    state["last_decision"] = now.isoformat()
    state["last_updated"]  = now.isoformat()
    save_state(state)
    print("  [保存] 状態を更新しました")


if __name__ == "__main__":
    run_cycle()
