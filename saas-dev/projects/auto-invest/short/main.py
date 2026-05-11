"""
SHORT bot — スキャルピング戦略
Kelly基準ポジションサイジング + ドローダウン制御 + 拡張シグナル
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(1, str(Path(__file__).parent.parent / "shared"))

from collector import collect_all
from analyzer import RuleBasedAnalyzer
from portfolio import Portfolio
from logger import init_db, save_trade, save_snapshot, get_performance_stats, get_recent_trades
from learner import print_report, learn
from summary import write_summary
from kelly import KellyCriterion, DrawdownManager
from entry_optimizer import check_entry_quality
from ml_predictor import refresh_predictor

COIN            = "bitcoin"
INITIAL_BALANCE = 10000.0

_kelly   = KellyCriterion(fraction=0.25)
_dd_mgr  = None  # main()で初期化


def run_cycle(portfolio: Portfolio, analyzer: RuleBasedAnalyzer):
    global _dd_mgr

    print(f"\n{'='*55}")
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC]")

    # 1. 情報収集
    print("[1] データ収集中...")
    market_data = collect_all(COIN)
    save_snapshot(market_data)

    price = market_data.get("technicals", {}).get("current_price")
    if not price:
        print("[!] 価格データなし。スキップします。")
        return

    t     = market_data.get("technicals", {})
    fg    = market_data.get("fear_greed", {}) or {}
    deriv = market_data.get("derivatives", {})

    print(f"    BTC価格: ${price:,.2f}")
    print(f"    RSI={t.get('rsi')} | MACD={t.get('macd')} | ADX={t.get('adx')}"
          f" | F&G={fg.get('value')}")
    if deriv:
        fr = deriv.get("funding_rate")
        oi = deriv.get("open_interest")
        ls = deriv.get("long_short_ratio")
        print(f"    FR={fr:.4f}% | OI={oi:,.0f}BTC | L/S={ls:.2f}"
              if fr is not None and oi is not None and ls is not None
              else f"    デリバティブ: {deriv}")

    # 2. Kelly基準ポジションサイジング
    recent_trades = get_recent_trades(30)
    short_trades  = [t for t in recent_trades if t.get("bot_type") == "SHORT"]
    win_rate, avg_win, avg_loss = KellyCriterion.from_trade_history(short_trades)
    kelly_invest = _kelly.position_size_usd(portfolio.balance, win_rate, avg_win, avg_loss)

    # ドローダウン制御
    pv        = portfolio.portfolio_value({COIN: price})
    dd_mult   = _dd_mgr.exposure_multiplier(pv)
    dd_status = _dd_mgr.status(pv)
    kelly_invest *= dd_mult

    print(f"\n[Kelly] 勝率={win_rate:.0%} | 平均利益=${avg_win:.2f} | 平均損失=${avg_loss:.2f}")
    print(f"        最適投資額=${kelly_invest:,.2f} | {dd_status}")

    if dd_mult == 0.0:
        print("[DD制御] ドローダウン過大 → 新規エントリー停止")

    # 3. シグナル分析
    analysis   = analyzer.analyze(market_data)
    decision   = analysis["decision"]
    confidence = analysis["confidence"]
    risk       = analysis["risk_level"]
    score      = analysis["total_score"]

    print(f"\n[2] シグナル分析:")
    for sig in analysis.get("signals", []):
        mark = "+" if sig["score"] > 0 else ("-" if sig["score"] < 0 else " ")
        print(f"    [{mark}] {sig['reason']}")
    print(f"\n    判断: {decision}  スコア={score:+.2f}  確信度={confidence:.0%}  リスク={risk}")

    # 4. スキャルピング出口チェック（最優先）
    should_exit, exit_reason = portfolio.check_scalp_exits(
        COIN, price,
        take_profit_pct=0.08, stop_loss_pct=0.05,
        trailing_pct=0.03, tight_trigger=0.05, tight_pct=0.02,
    )
    if should_exit:
        decision = "SELL"
        analysis["reasoning"] = exit_reason

    # 5. エントリー品質チェック（BUY時のみ）
    from regime import detect_regime
    regime_info = {}
    if decision == "BUY":
        # regimeをtechnicalsから簡易推定
        adx_val = t.get("adx", 0) or 0
        di_plus  = t.get("di_plus", 0) or 0
        di_minus = t.get("di_minus", 0) or 0
        if adx_val > 25:
            regime_str = "BULL" if di_plus > di_minus else "BEAR"
        elif t.get("ma20") and t.get("ma50") and price:
            regime_str = ("BULL" if price > t.get("ma50",0) else
                          "BEAR" if price < t.get("ma50",0) else "RANGE")
        else:
            regime_str = "RANGE"

        should_enter, eq_score, eq_reason = check_entry_quality(t, regime_str)
        print(f"\n[Entry] {eq_reason}")
        if not should_enter:
            print(f"[Entry] エントリー品質不足(score={eq_score:.2f}) → HOLD")
            decision = "HOLD"

    # 6. 売買実行
    record = None
    if decision == "BUY" and dd_mult > 0:
        record = portfolio.buy(COIN, price, analysis["reasoning"], confidence, risk,
                               invest_usd=kelly_invest)
        if record:
            print(f"\n[BUY]  {record.shares:.6f} BTC @ ${price:,.2f}"
                  f"  投資=${record.value_usd:,.2f} (Kelly={kelly_invest:,.2f})")
    elif decision == "SELL":
        record = portfolio.sell(COIN, price, analysis["reasoning"], confidence, risk)
        if record:
            sign = "+" if record.pnl >= 0 else ""
            print(f"\n[SELL] {record.shares:.6f} BTC @ ${price:,.2f}  PnL={sign}${record.pnl:,.2f}")

    if record:
        record.bot_type     = "SHORT"
        record.signals_json = analysis.get("signals")
        save_trade(record)
        # 取引後にMLモデルを再学習
        try:
            refresh_predictor("SHORT")
            print("    [ML] モデル再学習完了")
        except Exception:
            pass
    else:
        print(f"\n[{'SKIP' if decision != 'HOLD' else 'HOLD'}] 売買なし")

    # 6. パフォーマンス表示
    summary = portfolio.summary({COIN: price})
    stats   = get_performance_stats()
    print(f"\n[PF]  資産: ${summary['portfolio_value']:,.2f} "
          f"({'+' if summary['total_return_pct'] >= 0 else ''}{summary['total_return_pct']}%)")
    print(f"      確定損益: ${summary['realized_pnl']:,.2f}  "
          f"取引回数: {summary['total_trades']}")


def main():
    global _dd_mgr
    print("[SHORT] スキャルピングボット起動")
    init_db()

    portfolio = Portfolio(
        initial_balance=INITIAL_BALANCE,
        risk_per_trade=0.10,       # Kelly未使用時のフォールバック
        max_positions=1,
        state_file="portfolio_short.json",
        take_profit_pct=0.08,
        stop_loss_pct=0.05,
        trailing_stop_pct=0.03,
    )

    _dd_mgr = DrawdownManager(portfolio.initial_balance)

    analyzer = RuleBasedAnalyzer()
    try:
        run_cycle(portfolio, analyzer)
        learn("SHORT")
        print_report("SHORT")
    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()
    finally:
        portfolio._save()
        write_summary("SHORT")


if __name__ == "__main__":
    main()
