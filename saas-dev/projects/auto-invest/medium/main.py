"""
MEDIUM bot — ラダー利確 + Kelly基準 + 統計的裁定 + マクロフィルター
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(1, str(Path(__file__).parent.parent / "shared"))
sys.path.insert(2, str(Path(__file__).parent.parent / "src"))

from collector import collect_all
from analyzer import MediumTermAnalyzer
from portfolio import Portfolio
from logger import init_db, save_trade, save_snapshot, get_recent_trades
from summary import write_summary
from learner import learn, print_report
from kelly import KellyCriterion, DrawdownManager
from ml_predictor import refresh_predictor

INITIAL_BALANCE  = 10000.0
LADDER_TARGETS   = [(0.05, 0.33), (0.10, 0.33), (0.15, 1.0)]  # +5%→33%, +10%→33%, +15%→全売

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
    r.bot_type      = "MEDIUM"
    r.signals_json  = signals
    return r


def run_cycle(portfolio: Portfolio, analyzer: MediumTermAnalyzer):
    global _dd_mgr
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n{'='*55}")
    print(f"[MEDIUM] {now}")
    print("[1] 日足データ収集中...")

    data = collect_all()
    save_snapshot(data)

    assets  = data.get("assets", {})
    prices  = {t: info.get("price", 0) for t, info in assets.items() if info.get("price")}
    stat_arb = data.get("stat_arb", {})
    macro    = data.get("macro", {})

    print("    市場状況:")
    for ticker, info in assets.items():
        if info:
            gc   = " [GC]" if info.get("golden_cross") else ""
            dc   = " [DC]" if info.get("death_cross")  else ""
            held = " ★保有" if ticker in portfolio.positions else ""
            adx  = info.get("adx")
            adx_s = f" ADX={adx:.0f}" if adx else ""
            print(f"    {ticker}: ${info.get('price','N/A')} "
                  f"RSI={info.get('rsi','N/A')}{adx_s}{gc}{dc}{held}")

    if stat_arb:
        print(f"    BTC-ETH裁定: Z={stat_arb.get('z_score','N/A')} "
              f"({stat_arb.get('signal','N/A')})")

    vix = macro.get("VIX", {})
    tnx = macro.get("TNX", {})
    if vix: print(f"    VIX={vix.get('value','N/A')}")
    if tnx: print(f"    US10Y={tnx.get('value','N/A')}%")

    # 2. Kelly基準ポジションサイジング
    recent  = get_recent_trades(30)
    m_trades = [t for t in recent if t.get("bot_type") == "MEDIUM"]
    win_rate, avg_win, avg_loss = KellyCriterion.from_trade_history(m_trades)

    pv_prices = {t: prices.get(t, info.get("price", 0))
                 for t, info in assets.items()}
    pv = portfolio.portfolio_value(pv_prices)
    dd_mult = _dd_mgr.exposure_multiplier(pv)
    print(f"\n[Kelly] 勝率={win_rate:.0%} | {_dd_mgr.status(pv)}")

    # ── 保有中ポジションの売り判断 ────────────────────────
    for ticker in list(portfolio.positions.keys()):
        price = prices.get(ticker)
        if not price:
            continue

        # 1. ラダー利確
        should_l, fraction, l_reason, l_key = portfolio.check_ladder_exits(
            ticker, price, LADDER_TARGETS)
        if should_l:
            rec = portfolio.partial_sell(ticker, price, fraction, l_reason, 0.9, "LOW",
                                         ladder_key=l_key)
            if rec:
                save_trade(make_trade_record(rec))
                sign = "+" if rec.pnl >= 0 else ""
                print(f"\n[SELL] {ticker} @ ${price:,.2f}  {l_reason}  PnL={sign}${rec.pnl:,.2f}")
            continue

        # 2. 損切り・トレーリング
        should_s, s_reason = portfolio.check_stop_exits(ticker, price)
        if should_s:
            rec = portfolio.sell(ticker, price, s_reason, 0.9, "LOW")
            if rec:
                save_trade(make_trade_record(rec))
                sign = "+" if rec.pnl >= 0 else ""
                print(f"\n[SELL] {ticker} @ ${price:,.2f}  {s_reason}  PnL={sign}${rec.pnl:,.2f}")
            continue

        # 3. テクニカル悪化による売り
        info = assets.get(ticker, {})
        if info:
            should_sell = (
                info.get("death_cross") or
                (info.get("above_ma50") is False and info.get("above_ma200") is False)
            )
            if should_sell:
                rec = portfolio.sell(ticker, price, "デスクロスまたはMA50/200下抜け", 0.7, "MEDIUM")
                if rec:
                    save_trade(make_trade_record(rec))
                    sign = "+" if rec.pnl >= 0 else ""
                    print(f"\n[SELL] {ticker} @ ${price:,.2f}  PnL={sign}${rec.pnl:,.2f}")

    # ── 新規BUY判断 ───────────────────────────────────────
    analysis  = analyzer.analyze(data)
    decision  = analysis["decision"]
    primary   = data.get("primary_ticker", "BTC-USD")

    print(f"\n[2] シグナル分析 (対象: {primary}):")
    for s in analysis.get("signals", []):
        mark = "+" if s["score"] > 0 else ("-" if s["score"] < 0 else " ")
        print(f"    [{mark}] {s['reason']}")
    print(f"\n    判断: {decision}  スコア={analysis['total_score']:+.1f}  "
          f"確信度={analysis['confidence']:.0%}  リスク={analysis['risk_level']}")

    if decision == "BUY" and dd_mult > 0:
        price = prices.get(primary)
        if price:
            kelly_invest = _kelly.position_size_usd(
                portfolio.balance, win_rate, avg_win, avg_loss) * dd_mult
            rec = portfolio.buy(primary, price, analysis["reasoning"],
                                analysis["confidence"], analysis["risk_level"],
                                invest_usd=kelly_invest)
            if rec:
                save_trade(make_trade_record(rec, signals=analysis.get("signals")))
                print(f"\n[BUY]  {primary} {rec.shares:.6f} @ ${price:,.2f}"
                      f"  (Kelly=${kelly_invest:,.2f})")
            else:
                print(f"\n[SKIP] {primary} 既保有またはポジション上限")
    elif dd_mult == 0.0:
        print(f"\n[DD制御] ドローダウン過大 → 新規エントリー停止")
    else:
        print(f"\n[HOLD] 売買なし")

    # ── サマリー ──────────────────────────────────────────
    summary = portfolio.summary(pv_prices)
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
    print("[START] 中期ボット起動（ラダー利確 + Kelly + マクロフィルター）")
    init_db()
    portfolio = Portfolio(
        initial_balance=INITIAL_BALANCE,
        risk_per_trade=0.15,
        max_positions=5,
        state_file="portfolio_medium.json",
    )
    _dd_mgr = DrawdownManager(portfolio.initial_balance)

    analyzer = MediumTermAnalyzer()
    try:
        run_cycle(portfolio, analyzer)
        refresh_predictor("MEDIUM")
        learn("MEDIUM")
        print_report("MEDIUM")
    except Exception as e:
        import traceback
        print(f"[ERROR] {e}")
        traceback.print_exc()
    finally:
        portfolio._save()
        write_summary("MEDIUM")


if __name__ == "__main__":
    main()
