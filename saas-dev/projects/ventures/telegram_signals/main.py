"""
ventures/telegram_signals/main.py
毎日実行: シグナル配信 → 登録者数計測 → Geminiで最適化
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.optimizer import optimize
from shared.metrics import load_state, save_state, record_performance, apply_optimization
from signal_reader import read_signals, format_message
from bot import send_message, get_member_count

# 3日ごとにローテーションするプロダクトCTA
_PRODUCT_PROMOS = [
    ("🧠 ADHD Unlocked",      "50 AI prompts that work WITH your ADHD brain — task breakdown, focus systems, routine building. Not generic advice.", "https://ryuumg.gumroad.com/l/akikab"),
    ("🚀 AI Content Boost",   "50 prompts for content creators: viral hooks, content calendars, repurposing systems. Publish more, burn out less.", "https://ryuumg.gumroad.com/l/qhanl"),
    ("🛍️ Etsy Seller Boost", "50 prompts for Etsy sellers: SEO titles, product descriptions, customer messages. Save hours every week.", "https://ryuumg.gumroad.com/l/nnijeb"),
    ("🎨 DesignGenie",        "50 AI prompts for graphic designers: creative briefs, client communication, portfolio copy. Less admin, more design.", "https://ryuumg.gumroad.com/l/zkiwh"),
    ("🔥 Viral Content",      "50 prompts reverse-engineered from viral posts. Hooks, storytelling frameworks, trend newsjacking.", "https://ryuumg.gumroad.com/l/rboqqr"),
    ("✏️ Procreate AI",       "50 AI prompts for Procreate artists: composition, color palettes, character design, finding your style.", "https://ryuumg.gumroad.com/l/yugogd"),
]


def _maybe_send_product_promo(posts_sent: int) -> None:
    """3日ごとにシグナルの後にプロダクトプロモを配信。"""
    if posts_sent % 3 != 0:
        return
    idx = (posts_sent // 3) % len(_PRODUCT_PROMOS)
    name, desc, url = _PRODUCT_PROMOS[idx]
    msg = (
        f"\n\n💼 <b>AI Tool Spotlight</b>\n\n"
        f"<b>{name}</b>\n{desc}\n\n"
        f"📦 <a href='{url}'>Get it on Gumroad →</a> (one-time · instant download)\n"
        f"🆓 Free tools &amp; guides: https://ryuu321.github.io/ai-holdings/start.html"
    )
    send_message(msg)
    print(f"  製品プロモ配信: {name}")

STATE_PATH = Path(__file__).parent / "state.json"

DEFAULT_STATE = {
    "venture": "telegram_signals",
    "params": {
        "include_bots": ["SHORT", "MEDIUM", "LONG", "VOLT", "ATTACK", "MACRO"],
        "note_cta": True,
        "sort_by_pnl": True,
    },
    "performance_history": [],
    "learnings": [],
    "last_optimized": None,
    "posts_sent": 0,
}


def main():
    print(f"\n{'='*50}")
    print("[telegram_signals] シグナル配信 開始")
    state = load_state(STATE_PATH) or DEFAULT_STATE
    params = state.get("params", DEFAULT_STATE["params"])

    # Step1: 配信前の登録者数
    subs_before = get_member_count()
    print(f"  登録者数: {subs_before if subs_before >= 0 else '取得不可'}")

    # Step2: シグナル生成
    signals = read_signals(params.get("include_bots"))
    if not signals:
        print("  [WARN] ポートフォリオデータなし → スキップ")
        return

    message = format_message(signals, params)
    ok = send_message(message)
    if ok:
        state["posts_sent"] = state.get("posts_sent", 0) + 1
        print(f"  配信完了（通算{state['posts_sent']}件）")
        _maybe_send_product_promo(state["posts_sent"])
    else:
        print("  配信スキップ（Bot未設定 or エラー）")

    # Step3: 事後計測
    subs_after = get_member_count()
    growth = (subs_after - subs_before) if subs_before >= 0 and subs_after >= 0 else 0

    # Step4: メトリクス記録
    state = record_performance(state, {
        "subscribers": max(subs_after, 0),
        "daily_growth": growth,
        "post_sent": 1 if ok else 0,
        "bots_included": len(signals),
    })

    # Step5: 7日分たまったらGemini最適化
    if len(state.get("performance_history", [])) >= 7:
        print("  [最適化] Gemini分析中...")
        opt = optimize("telegram_signals", state)
        state = apply_optimization(state, opt)
        print(f"  洞察: {opt['insight']}")
        print(f"  次のアクション: {opt['action']}")

    save_state(STATE_PATH, state)
    print(f"[完了] 登録者: {max(subs_after, 0)} (Δ{growth:+d})")


if __name__ == "__main__":
    main()
