"""
ボット実行後に data/summary.json を書き出す
ダッシュボードはこのJSONをGitHub raw URLから直接読む
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH  = DATA_DIR / "trades.db"


def write_summary(bot_type: str = None):
    """全ボットの状態をまとめてsummary.jsonに書き出す"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(timezone.utc).isoformat()

    # 既存のsummaryを読み込んでlast_run情報を引き継ぐ
    existing = {}
    out_path = DATA_DIR / "summary.json"
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    summary = {
        "updated_at": now_iso,
        "portfolios": {},
        "recent_trades": [],
        "stats": {},
    }

    # ── ポートフォリオ状態（Portfolio形式: LONG/MEDIUM/SHORT/MACRO）──
    for fname, label in [
        ("portfolio_long.json",   "LONG"),
        ("portfolio_medium.json", "MEDIUM"),
        ("portfolio_short.json",  "SHORT"),
        ("portfolio_macro.json",  "MACRO"),
    ]:
        path = DATA_DIR / fname
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                summary["portfolios"][label] = data
            except Exception:
                pass

    # ── ATTACK / VOLT（独自state形式 → Portfolio形式に正規化）──
    for fname, label in [
        ("portfolio_attack.json", "ATTACK"),
        ("portfolio_volt.json",   "VOLT"),
    ]:
        path = DATA_DIR / fname
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            cash    = raw.get("balance", 10000)
            init    = raw.get("initial_balance", 10000)
            last_dt = raw.get("last_updated") or raw.get("last_decision") or ""

            # ATTACK: position = {ticker, price, shares, cost, peak}
            pos_obj = raw.get("position")
            if pos_obj and isinstance(pos_obj, dict):
                ticker = pos_obj.get("ticker", "BTC-USD")
                positions = {
                    ticker: {
                        "shares":    pos_obj.get("shares", 0),
                        "buy_price": pos_obj.get("price", 0),
                        "cost":      pos_obj.get("cost", 0),
                        "peak":      pos_obj.get("peak", pos_obj.get("price", 0)),
                        "entry_date": pos_obj.get("entry_date", ""),
                    }
                }
            # VOLT: shares + ticker (top-level)
            elif raw.get("shares", 0) > 1e-9:
                ticker = raw.get("ticker", "BTC-USD")
                shares = raw.get("shares", 0)
                cb     = raw.get("cost_basis", 0)
                avg_p  = cb / shares if shares > 0 else 0
                positions = {
                    ticker: {
                        "shares":    shares,
                        "buy_price": avg_p,
                        "cost":      cb,
                    }
                }
            else:
                positions = {}

            summary["portfolios"][label] = {
                "balance":         cash,
                "initial_balance": init,
                "positions":       positions,
                "last_run":        last_dt,
                "trade_count":     raw.get("trade_count", 0),
                "total_realized_pnl": raw.get("total_realized_pnl", 0),
            }
        except Exception as e:
            print(f"[SUMMARY] {fname} 読み込みエラー: {e}")

    # ── 直近トレード（DBから取得 + 既存summary.jsonの履歴を引き継ぎ）──
    # trades.dbはgit管理外のため、既存summary.jsonの履歴を蓄積する
    existing_trades = existing.get("recent_trades", [])
    existing_keys = {(t.get("timestamp","")[:19], t.get("coin",""), t.get("bot_type","")) for t in existing_trades}

    new_trades = []
    total_buys = total_sells = wins = 0
    realized_pnl = 0.0

    if DB_PATH.exists():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT timestamp, action, coin, price, amount, value_usd,
                       balance_after, pnl, reasoning, confidence, risk_level,
                       COALESCE(bot_type, 'SHORT') as bot_type
                FROM trades
                WHERE action IN ('BUY', 'SELL')
                ORDER BY timestamp DESC LIMIT 50
            """)
            for r in cur.fetchall():
                row = dict(r)
                # reasoning を100字に切り詰め
                if row.get("reasoning") and len(row["reasoning"]) > 100:
                    row["reasoning"] = row["reasoning"][:100] + "…"
                key = (row["timestamp"][:19], row["coin"], row["bot_type"])
                if key not in existing_keys:
                    new_trades.append(row)
                    existing_keys.add(key)
        except Exception:
            pass
        finally:
            conn.close()

    # BUY/SELLのみ蓄積、最大50件
    merged = new_trades + [t for t in existing_trades if t.get("action") in ("BUY","SELL")]
    merged.sort(key=lambda t: t.get("timestamp",""), reverse=True)
    summary["recent_trades"] = merged[:50]

    # statsを全履歴から再計算
    for t in merged:
        if t.get("action") == "BUY":
            total_buys += 1
        elif t.get("action") == "SELL":
            total_sells += 1
            realized_pnl += t.get("pnl", 0) or 0
            if (t.get("pnl") or 0) > 0:
                wins += 1
    summary["stats"] = {
        "total_buys":   total_buys,
        "total_sells":  total_sells,
        "realized_pnl": round(realized_pnl, 2),
        "win_rate":     round(wins / total_sells * 100, 1) if total_sells else 0.0,
    }

    out = DATA_DIR / "summary.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SUMMARY] data/summary.json 書き出し完了")
