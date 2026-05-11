"""
投資ボットのportfolio JSONからシグナルを読み取ってメッセージを生成
"""
import json
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent.parent / "auto-invest" / "data"

NOTE_OUTPUT = Path(__file__).parent.parent.parent.parent / "note-biz" / "output"

BOT_META = {
    "LONG":   {"emoji": "🐢", "strategy": "長期トレンドフォロー"},
    "MEDIUM": {"emoji": "⚡", "strategy": "中期モメンタム"},
    "SHORT":  {"emoji": "🎯", "strategy": "短期スキャルピング"},
    "VOLT":   {"emoji": "🛡️", "strategy": "守備型VolTargeting"},
    "ATTACK": {"emoji": "⚔️", "strategy": "攻撃型MA200+RSI"},
    "MACRO":  {"emoji": "🌍", "strategy": "マクロファンダメンタルズ"},
}


def _latest_note_title() -> str:
    if not NOTE_OUTPUT.exists():
        return ""
    files = sorted(NOTE_OUTPUT.glob("*.md"), reverse=True)
    for f in files:
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        title = lines[0].lstrip("# ").strip() if lines else ""
        if title:
            return title[:40] + ("..." if len(title) > 40 else "")
    return ""


def read_signals(include_bots: list = None) -> dict:
    summary_path = DATA_DIR / "summary.json"
    if not summary_path.exists():
        return {}

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    portfolios = data.get("portfolios", {})

    signals = {}
    for bot_name, portfolio in portfolios.items():
        if include_bots and bot_name not in include_bots:
            continue
        balance = portfolio.get("balance", 0)
        initial = portfolio.get("initial_balance", 10000)
        pnl_pct = (balance / initial - 1) * 100 if initial else 0
        positions = portfolio.get("positions", {})
        short_pos = portfolio.get("short_positions", {})

        long_tickers = list(positions.keys())
        short_tickers = [f"↓{t}" for t in short_pos.keys()]
        all_tickers = (long_tickers + short_tickers)[:4]

        signals[bot_name] = {
            **BOT_META.get(bot_name, {"emoji": "📊", "strategy": ""}),
            "pnl_pct": pnl_pct,
            "balance": balance,
            "tickers": all_tickers,
            "position_count": len(positions) + len(short_pos),
        }
    return signals


def format_message(signals: dict, params: dict) -> str:
    now_jst = datetime.now(timezone.utc)
    date_str = now_jst.strftime("%Y-%m-%d")
    lines = [f"<b>📈 AI投資シグナル日報 {date_str}</b>\n"]

    # P&L順にソート（成績上位を上に）
    sorted_bots = sorted(signals.items(), key=lambda x: x[1]["pnl_pct"], reverse=True)

    for bot_name, s in sorted_bots:
        emoji = s["emoji"]
        pnl = s["pnl_pct"]
        sign = "+" if pnl >= 0 else ""
        bar = "🟢" if pnl >= 0 else "🔴"
        tickers_str = "・".join(s["tickers"]) if s["tickers"] else "現金待機"

        lines.append(f"{bar} <b>{emoji} {bot_name}</b>  累計 {sign}{pnl:.1f}%")
        lines.append(f"   保有: {tickers_str}")
        lines.append("")

    lines.append("─────────────────────")

    # 最新note記事をピックアップして紹介
    note_title = _latest_note_title()
    if note_title:
        lines.append(f"📝 今日のnote: <i>{note_title}</i>")

    if params.get("note_cta"):
        lines.append("💡 戦略詳細・記事はnote → @takumi_ai_f / @yuuki_nisa / @ken_nenshu_up")
        lines.append("📌 このチャンネルをフォローして毎朝シグナルを受け取ろう")

    return "\n".join(lines)
