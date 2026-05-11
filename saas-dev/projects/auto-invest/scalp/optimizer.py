"""
SCALP optimizer — 日次AI最適化
トレード結果を分析してGroqが戦略パラメータを毎日書き換える
目標: 月利30%
"""
import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

DATA_DIR      = Path(__file__).parent.parent / "data"
TRADES_FILE   = DATA_DIR / "scalp_trades.json"
STRATEGY_FILE = DATA_DIR / "scalp_strategy.json"
OPT_LOG_FILE  = DATA_DIR / "scalp_optimizer_log.json"

GROQ_KEY = os.environ.get("GROQ_API_KEY")

# パラメータ安全範囲（AIが逸脱しても強制クランプ）
BOUNDS = {
    "rsi_period":       (5,    25),
    "rsi_oversold":     (20,   45),
    "rsi_overbought":   (55,   80),
    "bb_period":        (10,   30),
    "bb_std":           (1.5,  3.0),
    "stop_loss_pct":    (0.003, 0.025),
    "take_profit_pct":  (0.005, 0.040),
    "invest_pct":       (0.50, 0.95),
    "max_hold_minutes": (30,   480),
}

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


def load_trades() -> list:
    if TRADES_FILE.exists():
        try:
            return json.loads(TRADES_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def calc_metrics(trades: list) -> dict:
    if not trades:
        return {"total": 0, "win_rate": 0, "total_pnl_pct": 0}

    pnls   = [t["pnl_pct"] for t in trades]
    wins   = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # 直近7日
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent = [t for t in trades if t.get("exit_time", "") >= cutoff]

    # 最大ドローダウン
    cum = peak = max_dd = 0.0
    for p in pnls:
        cum += p / 100
        if cum > peak:
            peak = cum
        max_dd = max(max_dd, peak - cum)

    reasons = {}
    for t in trades:
        r = t.get("reason", "?")
        reasons[r] = reasons.get(r, 0) + 1

    return {
        "total":               len(trades),
        "win_rate":            round(len(wins) / len(trades) * 100, 1),
        "avg_win_pct":         round(sum(wins)   / len(wins),   3) if wins   else 0,
        "avg_loss_pct":        round(sum(losses) / len(losses), 3) if losses else 0,
        "total_pnl_pct":       round(sum(pnls), 3),
        "recent_7d_trades":    len(recent),
        "recent_7d_pnl_pct":   round(sum(t["pnl_pct"] for t in recent), 3),
        "max_drawdown_pct":    round(max_dd * 100, 2),
        "exit_reasons":        reasons,
        "avg_hold_min":        round(sum(t.get("hold_min", 0) for t in trades) / len(trades), 1),
    }


def validate(s: dict) -> dict:
    for key, (lo, hi) in BOUNDS.items():
        if key in s:
            s[key] = max(lo, min(hi, float(s[key]) if isinstance(s[key], (int, float)) else lo))
    # TP は必ず SL×1.5 以上
    s["take_profit_pct"] = max(s["take_profit_pct"], s["stop_loss_pct"] * 1.5)
    return s


def run_optimizer():
    now     = datetime.now(timezone.utc)
    trades  = load_trades()
    current = load_strategy()
    metrics = calc_metrics(trades)

    print(f"\n[SCALP Optimizer] {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  総トレード: {metrics['total']}  勝率: {metrics['win_rate']}%  累計: {metrics['total_pnl_pct']:+.2f}%")
    print(f"  直近7日: {metrics['recent_7d_trades']}回 / {metrics['recent_7d_pnl_pct']:+.2f}%  MaxDD: {metrics.get('max_drawdown_pct',0):.1f}%")

    if not GROQ_KEY:
        print("  [SKIP] GROQ_API_KEY未設定")
        return

    if metrics["total"] < 3:
        print("  [SKIP] データ不足（3トレード未満）— 初期パラメータで継続")
        # 初回はデフォルト戦略を保存だけしておく
        if not STRATEGY_FILE.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            STRATEGY_FILE.write_text(json.dumps(DEFAULT_STRATEGY, indent=2, ensure_ascii=False), encoding="utf-8")
        return

    from groq import Groq
    client = Groq(api_key=GROQ_KEY)

    recent_trades = trades[-30:]
    trades_text = "\n".join(
        f"  #{t['id']} {t.get('exit_time','')[:16]} "
        f"entry=${t['entry_price']:,.0f} exit=${t['exit_price']:,.0f} "
        f"PnL={t['pnl_pct']:+.2f}% {t.get('hold_min',0):.0f}分 [{t['reason']}] "
        f"RSIentry={t.get('rsi_at_entry','?')}"
        for t in recent_trades
    )

    prompt = f"""あなたはBTCスキャルピングボットの戦略最適化AIです。
目標: 月利30%（ペーパートレード、ペナルティなし）

現在の戦略 (v{current.get('version',1)}):
{json.dumps(current, indent=2, ensure_ascii=False)}

パフォーマンス:
- 総トレード: {metrics['total']}
- 勝率: {metrics['win_rate']}%
- 平均利益: +{metrics['avg_win_pct']}% / 平均損失: {metrics['avg_loss_pct']}%
- 累計PnL: {metrics['total_pnl_pct']:+.2f}%
- 直近7日: {metrics['recent_7d_trades']}回 / {metrics['recent_7d_pnl_pct']:+.2f}%
- 最大ドローダウン: {metrics.get('max_drawdown_pct',0):.1f}%
- 決済理由: {metrics.get('exit_reasons',{})}
- 平均保有: {metrics.get('avg_hold_min',0):.0f}分

直近トレード:
{trades_text}

月利30%達成のために今日変更すべきパラメータを分析してください。
考慮すべき点:
- SLが多いならrsi_oversoldを下げてエントリー条件を厳しく、またはstop_loss_pctを拡大
- タイムアウトが多いならmax_hold_minutesを短縮またはtake_profit_pctを下げる
- 勝率<40%ならエントリー条件を絞る（bb+rsi両方必須など）
- トレード数が少なすぎ(<3/日)なら条件を緩める

パラメータ範囲:
rsi_period[5-25] rsi_oversold[20-45] rsi_overbought[55-80]
bb_period[10-30] bb_std[1.5-3.0]
stop_loss_pct[0.003-0.025] take_profit_pct[0.005-0.040]
invest_pct[0.50-0.95] max_hold_minutes[30-480]
require_bb/require_rsi/require_volume_spike: true/false

JSONのみ出力（説明文・コードブロック不要）:
{{"reasoning":"変更理由を2-3文","strategy":{{"rsi_period":14,"rsi_oversold":35,"rsi_overbought":65,"bb_period":20,"bb_std":2.0,"stop_loss_pct":0.008,"take_profit_pct":0.015,"invest_pct":0.80,"max_hold_minutes":120,"require_bb":true,"require_rsi":true,"require_volume_spike":false}}}}"""

    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"  [ERROR] Groq API: {e}")
        return

    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        print(f"  [ERROR] JSONなし: {raw[:200]}")
        return
    try:
        result = json.loads(m.group())
    except json.JSONDecodeError:
        # 修復試行
        s = m.group().rstrip().rstrip(",")
        s += "}" * max(0, s.count("{") - s.count("}"))
        try:
            result = json.loads(s)
        except Exception:
            print(f"  [ERROR] JSONパース失敗")
            return

    new_params = result.get("strategy", {})
    reasoning  = result.get("reasoning", "")
    if not new_params:
        print("  [ERROR] strategyキーなし")
        return

    updated = {**current, **new_params}
    updated["version"]    = current.get("version", 1) + 1
    updated["updated_at"] = now.isoformat()
    updated = validate(updated)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STRATEGY_FILE.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  [更新] v{current.get('version',1)} → v{updated['version']}")
    print(f"  理由: {reasoning}")
    print(f"  SL={updated['stop_loss_pct']*100:.1f}% TP={updated['take_profit_pct']*100:.1f}% RSI<{updated['rsi_oversold']} BB={updated['bb_std']} hold={updated['max_hold_minutes']}min")

    # 最適化ログ（直近30件）
    opt_log = []
    if OPT_LOG_FILE.exists():
        try:
            opt_log = json.loads(OPT_LOG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    opt_log.append({
        "timestamp": now.isoformat(),
        "version":   updated["version"],
        "reasoning": reasoning,
        "metrics":   metrics,
        "strategy":  updated,
    })
    OPT_LOG_FILE.write_text(json.dumps(opt_log[-30:], indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    run_optimizer()
