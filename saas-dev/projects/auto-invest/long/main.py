"""
LONG bot — DCA週次利確 + Kelly基準 + VIX/M2マクロフィルター
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(1, str(Path(__file__).parent.parent / "shared"))
sys.path.insert(2, str(Path(__file__).parent.parent / "src"))

from collector import collect_all
from analyzer import LongTermAnalyzer
from portfolio import Portfolio
from logger import init_db, save_trade, save_snapshot, get_recent_trades
from summary import write_summary
from learner import learn, print_report
from kelly import KellyCriterion, DrawdownManager
from ml_predictor import refresh_predictor

INITIAL_BALANCE = 10000.0
SELL_THRESHOLD  = -2

_kelly  = KellyCriterion(fraction=0.25)
_dd_mgr = None


def make_trade_record(rec, signals=None):
    class Compat: pass
    r = Compat()
    r.timestamp     = rec.timestamp
    r.action        = rec.action
    r.coin          = rec.ticker
    r.price         = rec.price
    r.amount        = rec.shares
    r.value_usd     = rec.value_usd
    r.balance_after = rec.balance_after
    r.pnl           = rec.pnl
    r.reasoning     = rec.reasoning
    r.confidence    = rec.confidence
    r.risk_level    = rec.risk_level
    r.bot_type      = "LONG"
    r.signals_json  = signals
    return r


def run_cycle(portfolio: Portfolio, analyzer: LongTermAnalyzer):
    global _dd_mgr
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*55}")
    print(f"[LONG] {now}")
    print("[1] ファンダメンタルズ + マクロ収集中...")

    data   = collect_all()
    save_snapshot(data)

    scores = data.get("scores", {})
    funds  = data.get("fundamentals", {})
    macro_i = data.get("macro_indicators", {})
    m2     = data.get("m2", {})
    prices = {t: f.get("price", 0) for t, f in funds.items() if f.get("price")}

    # マクロ状況表示
    vix = macro_i.get("VIX", {})
    tnx = macro_i.get("US10Y", {})
    dxy = macro_i.get("DXY", {})
    if vix: print(f"    VIX={vix.get('value','N/A')}")
    if tnx: print(f"    US10Y={tnx.get('value','N/A')}%")
    if dxy: print(f"    DXY={dxy.get('value','N/A')}")
    if m2:  print(f"    M2 YoY={m2.get('yoy_pct','N/A')}% ({m2.get('trend','N/A')})")

    print("    銘柄スコアランキング:")
    for ticker, score in sorted(scores.items(), key=lambda x: -x[1])[:5]:
        f    = funds.get(ticker, {})
        held = "★保有" if ticker in portfolio.positions else ""
        vm   = f.get("vol_momentum")
        vm_s = f" VolMom={vm:.2f}" if vm else ""
        print(f"    [{score:+d}] {ticker} PE={f.get('pe_ratio','N/A')} "
              f"成長={f.get('revenue_growth','N/A')}{vm_s} {held}")

    # 2. Kelly基準ポジションサイジング
    recent   = get_recent_trades(30)
    l_trades = [t for t in recent if t.get("bot_type") == "LONG"]
    win_rate, avg_win, avg_loss = KellyCriterion.from_trade_history(l_trades)

    pv      = portfolio.portfolio_value(prices)
    dd_mult = _dd_mgr.exposure_multiplier(pv)
    print(f"\n[Kelly] 勝率={win_rate:.0%} | {_dd_mgr.status(pv)}")

    # ── 保有中ポジションの売り判断 ────────────────────────
    for ticker in list(portfolio.positions.keys()):
        price = prices.get(ticker)
        if not price:
            continue

        # 1. 損切り・トレーリング
        should_stop, stop_reason = portfolio.check_stop_exits(ticker, price)
        if should_stop:
            rec = portfolio.sell(ticker, price, stop_reason, 0.9, "LOW")
            if rec:
                save_trade(make_trade_record(rec))
                sign = "+" if rec.pnl >= 0 else ""
                print(f"[SELL] {ticker} @ ${price:,.2f}  {stop_reason}  PnL={sign}${rec.pnl:,.2f}")
            continue

        # 2. DCA週次利確（含み益時・7日ごとに20%売却）
        should_dca, dca_frac, dca_reason = portfolio.check_dca_sell(
            ticker, price, interval_days=7, fraction=0.20)
        if should_dca:
            rec = portfolio.partial_sell(ticker, price, dca_frac, dca_reason, 0.7, "MEDIUM",
                                         update_dca=True)
            if rec:
                save_trade(make_trade_record(rec))
                sign = "+" if rec.pnl >= 0 else ""
                print(f"[DCA]  {ticker} @ ${price:,.2f}  {dca_reason}  PnL={sign}${rec.pnl:,.2f}")
            continue

        # 3. ファンダスコア悪化による全売り
        score = scores.get(ticker, 0)
        if score <= SELL_THRESHOLD:
            rec = portfolio.sell(ticker, price, f"ファンダスコア={score}→売却基準以下", 0.7, "MEDIUM")
            if rec:
                save_trade(make_trade_record(rec))
                sign = "+" if rec.pnl >= 0 else ""
                print(f"[SELL] {ticker} @ ${price:,.2f}  PnL={sign}${rec.pnl:,.2f}")

    # ── 新規BUY判断 ───────────────────────────────────────
    analysis   = analyzer.analyze(data)
    rec_ticker = analysis.get("recommended")
    decision   = analysis["decision"]

    print(f"\n[2] シグナル分析 (推奨: {rec_ticker}):")
    for s in analysis.get("signals", []):
        mark = "+" if s["score"] > 0 else ("-" if s["score"] < 0 else " ")
        print(f"    [{mark}] {s['reason']}")
    print(f"\n    判断: {decision}  スコア={analysis['total_score']:+.1f}  "
          f"確信度={analysis['confidence']:.0%}  リスク={analysis['risk_level']}")

    if decision == "BUY" and rec_ticker and dd_mult > 0:
        price = prices.get(rec_ticker)
        if price:
            kelly_invest = _kelly.position_size_usd(
                portfolio.balance, win_rate, avg_win, avg_loss) * dd_mult
            rec = portfolio.buy(rec_ticker, price, analysis["reasoning"],
                                analysis["confidence"], analysis["risk_level"],
                                invest_usd=kelly_invest)
            if rec:
                save_trade(make_trade_record(rec, signals=analysis.get("signals")))
                print(f"\n[BUY]  {rec_ticker} {rec.shares:.4f}株 @ ${price:,.2f}"
                      f"  (Kelly=${kelly_invest:,.2f})")
            else:
                print(f"\n[SKIP] {rec_ticker} 既保有またはポジション上限")
        else:
            print(f"\n[!] {rec_ticker} の価格データなし")
    elif dd_mult == 0.0:
        print(f"\n[DD制御] ドローダウン過大 → 新規エントリー停止")
    else:
        print(f"\n[HOLD] 新規購入なし")

    # ── サマリー ──────────────────────────────────────────
    summary = portfolio.summary(prices)
    print(f"\n[PF]  総資産: ${summary['portfolio_value']:,.2f} "
          f"({'+' if summary['total_return_pct'] >= 0 else ''}{summary['total_return_pct']}%)")
    print(f"      現金: ${summary['cash_balance']:,.2f}  "
          f"保有: {summary['open_positions']}銘柄  "
          f"確定損益: ${summary['realized_pnl']:,.2f}")
    if summary["positions"]:
        for p in summary["positions"]:
            print(f"        {p}")


def main():
    global _dd_mgr
    print("[START] 長期ボット起動（DCA利確 + Kelly + VIX/M2マクロフィルター）")
    init_db()
    portfolio = Portfolio(
        initial_balance=INITIAL_BALANCE,
        risk_per_trade=0.15,
        max_positions=5,
        state_file="portfolio_long.json",
        take_profit_pct=0.50,   # DCA利確に任せるため高め
        stop_loss_pct=0.10,
        trailing_stop_pct=0.07,
    )
    _dd_mgr = DrawdownManager(portfolio.initial_balance)

    analyzer = LongTermAnalyzer()
    try:
        run_cycle(portfolio, analyzer)
        refresh_predictor("LONG")
        learn("LONG")
        print_report("LONG")
    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()
    finally:
        portfolio._save()
        write_summary("LONG")


if __name__ == "__main__":
    main()
