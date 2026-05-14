"""
AI Holdings ダッシュボード生成スクリプト
出力: docs/index.html
"""
import json
import sqlite3
import csv
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict

ROOT = Path(__file__).parent.parent
JST = timezone(timedelta(hours=9))

# ── データ収集 ─────────────────────────────────────────────

def collect_note():
    """note-auto: 投稿記事数・URL"""
    posts = []
    for acc_id in [1, 2, 3]:
        f = ROOT / f"saas-dev/projects/note-auto/state_{acc_id}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        for a in data.get("articles", []):
            if a.get("status") == "success" and a.get("url"):
                posts.append({
                    "date": a["date"],
                    "account": acc_id,
                    "title": a["title"],
                    "price": a.get("price", 0),
                    "url": a["url"],
                })
    return sorted(posts, key=lambda x: x["date"])


def collect_rakuten_room():
    """楽天ROOM: 日別出品数（CSV + daily_count.json を合算）"""
    by_date = defaultdict(int)
    total_override = None

    # CSV の posted_at（過去分）
    f = ROOT / "saas-dev/projects/rakuten-room/data/products.csv"
    if f.exists():
        try:
            with open(f, encoding="utf-8") as fp:
                for row in csv.DictReader(fp):
                    if row.get("posted", "").strip().lower() == "true":
                        date = row.get("posted_at", "")[:10]
                        if date:
                            by_date[date] += 1
        except Exception:
            pass

    # daily_count.json で上書き（GitHub Actionsが書く正確な値）
    dc = ROOT / "saas-dev/projects/rakuten-room/data/daily_count.json"
    if dc.exists():
        try:
            dc_data = json.loads(dc.read_text(encoding="utf-8"))
            total_override = dc_data.pop("_total_override", None)
            for date, count in dc_data.items():
                by_date[date] = count
        except Exception:
            pass

    result = [{"date": d, "count": c} for d, c in sorted(by_date.items())]
    return result, total_override


def collect_rakuten_af():
    """楽天AF: 日別記事投稿数・AB戦略"""
    db_path = ROOT / "saas-dev/projects/rakuten-af/data/rakuten_af.db"
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cols = [r[1] for r in conn.execute("PRAGMA table_info(articles)").fetchall()]
    if "strategy" in cols:
        rows = conn.execute("""
            SELECT DATE(created_at) as date, strategy, COUNT(*) as count
            FROM articles GROUP BY DATE(created_at), strategy ORDER BY date
        """).fetchall()
        result = [{"date": r["date"], "strategy": r["strategy"], "count": r["count"]} for r in rows]
    else:
        rows = conn.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as count
            FROM articles GROUP BY DATE(created_at) ORDER BY date
        """).fetchall()
        result = [{"date": r["date"], "strategy": "A", "count": r["count"]} for r in rows]
    conn.close()
    return result


def collect_af_stats(days: int = 30) -> list[dict]:
    """楽天AF 日別クリック・CVR・報酬データ"""
    f = ROOT / "saas-dev/projects/rakuten-af/data/af_stats.json"
    if not f.exists():
        return []
    try:
        all_stats = json.loads(f.read_text(encoding="utf-8"))
        today = datetime.now(JST).date()
        cutoff = (today - timedelta(days=days)).isoformat()
        return [s for s in all_stats if s["date"] >= cutoff]
    except Exception:
        return []


def collect_af_pdca() -> dict:
    """楽天AF PDCAログ（最新の最適化結果）"""
    f = ROOT / "saas-dev/projects/rakuten-af/data/pdca_log.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def collect_room_pdca() -> dict:
    """楽天ROOM PDCA（カテゴリ戦略・キャプション最適化結果）"""
    f = ROOT / "saas-dev/projects/rakuten-af/data/room_pdca_log.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def collect_note_pdca() -> dict:
    """note PDCA戦略（週次更新）"""
    f = ROOT / "saas-dev/projects/note-auto/pdca_strategy.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def collect_revenue():
    """手動入力収益データ"""
    f = ROOT / "dashboard/revenue.json"
    if not f.exists():
        return []
    data = json.loads(f.read_text(encoding="utf-8"))
    return data.get("entries", [])


def collect_kindle_kdp():
    """Kindle KDP: 出版済み書籍リスト"""
    f = ROOT / "saas-dev/projects/kindle-kdp/data/books.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []


def _fetch_live_price(ticker: str) -> float | None:
    """yfinanceでライブ価格を取得（失敗時はNone）"""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def collect_investment_bots():
    """投資ボット: summary.json + portfolio_*.json から最新PnL"""
    data_dir = ROOT / "saas-dev/projects/auto-invest/data"
    bots_map = {}

    # ライブ価格計算が必要なボット（単一ポジション・キャッシュ残高のみ記録）
    LIVE_PRICE_BOTS = {"ATTACK", "VOLT"}

    # summary.json（LONG/MEDIUM/SHORT/MACRO）
    sf = data_dir / "summary.json"
    if sf.exists():
        try:
            summary = json.loads(sf.read_text(encoding="utf-8"))
            for name, p in summary.get("portfolios", {}).items():
                if name in LIVE_PRICE_BOTS:
                    continue  # portfolio_*.json ブロックでライブ価格付きで処理
                cash      = p.get("balance", 0)
                init      = p.get("initial_balance", 10000)
                positions = p.get("positions", {})

                # equity = cash + ライブ価格×保有株数
                equity = cash
                for ticker, pos_data in positions.items():
                    shares = pos_data.get("shares", 0)
                    if shares > 0:
                        live  = _fetch_live_price(ticker)
                        price = live if live else pos_data.get("buy_price", 0)
                        equity += price * shares

                bots_map[name] = {
                    "name":      name,
                    "balance":   equity,
                    "initial":   init,
                    "pnl":       equity - init,
                    "pnl_pct":   (equity - init) / init * 100 if init else 0,
                    "positions": list(positions.keys()),
                    "last_run":  p.get("last_run", "")[:10],
                }
        except Exception:
            pass

    # portfolio_*.json（ATTACK / VOLT: ライブ価格でエクイティ計算）
    for pf in sorted(data_dir.glob("portfolio_*.json")):
        name = pf.stem.replace("portfolio_", "").upper()
        if name in bots_map:
            continue
        try:
            p    = json.loads(pf.read_text(encoding="utf-8"))
            cash = p.get("balance", 0)
            init = p.get("initial_balance", 10000)

            # ATTACK: position = {ticker, price, shares, cost} (単一ポジション)
            pos = p.get("position")
            if pos and isinstance(pos, dict):
                ticker = pos.get("ticker", "BTC-USD")
                sh     = pos.get("shares", 0)
                live   = _fetch_live_price(ticker)
                price  = live if live else pos.get("price", 0)
                equity = cash + price * sh
                pos_list = [ticker]
            else:
                # VOLT: shares + ticker でポジション推定
                sh     = p.get("shares", 0)
                ticker = p.get("ticker", "BTC-USD")
                if sh > 1e-9:
                    live   = _fetch_live_price(ticker)
                    cb     = p.get("cost_basis", 0)
                    price  = live if live else (cb / sh if sh > 0 else 0)
                    equity = cash + price * sh
                    pos_list = [ticker]
                else:
                    equity   = cash
                    pos_list = []

            last_run = (p.get("last_run") or p.get("last_updated") or "")[:10]

            bots_map[name] = {
                "name":      name,
                "balance":   equity,
                "initial":   init,
                "pnl":       equity - init,
                "pnl_pct":   (equity - init) / init * 100 if init else 0,
                "positions": pos_list,
                "last_run":  last_run,
            }
        except Exception:
            pass

    # SCALP: トレード統計を追加
    scalp_trades_f = data_dir / "scalp_trades.json"
    scalp_opt_f    = data_dir / "scalp_optimizer_log.json"
    for bot in bots_map.values():
        if bot["name"] != "SCALP":
            continue
        try:
            trades = json.loads(scalp_trades_f.read_text(encoding="utf-8")) if scalp_trades_f.exists() else []
            wins   = sum(1 for t in trades if t.get("pnl_pct", 0) > 0)
            bot["trade_count"] = len(trades)
            bot["win_rate"]    = round(wins / len(trades) * 100, 1) if trades else 0
            # 現在の戦略バージョン
            if scalp_opt_f.exists():
                log = json.loads(scalp_opt_f.read_text(encoding="utf-8"))
                bot["strategy_version"] = log[-1]["version"] if log else 1
        except Exception:
            pass

    return sorted(bots_map.values(), key=lambda x: x["name"])


def collect_gumroad() -> dict:
    """Gumroad: PDCAレポート・戦略データ"""
    data_dir = ROOT / "saas-dev/projects/gumroad/data"
    result = {
        "monthly_revenue_usd": 0.0,
        "goal_usd": 2000,
        "progress_pct": 0.0,
        "total_products": 0,
        "top_niches": [],
        "next_type": None,
        "next_niches": [],
        "generated_at": None,
    }
    pdca_f = data_dir / "pdca_report.json"
    if pdca_f.exists():
        try:
            pdca = json.loads(pdca_f.read_text(encoding="utf-8"))
            result["monthly_revenue_usd"] = pdca.get("monthly_revenue_usd", 0.0)
            result["goal_usd"]            = pdca.get("goal_usd", 2000)
            result["progress_pct"]        = pdca.get("progress_pct", 0.0)
            result["total_products"]      = pdca.get("total_published", pdca.get("total_products", 0))
            result["top_niches"]          = pdca.get("top_niches", [])
            ng = pdca.get("next_generation", {})
            result["next_type"]           = ng.get("type")
            result["next_niches"]         = ng.get("niches", [])
            result["generated_at"]        = (pdca.get("generated_at") or "")[:10]
        except Exception:
            pass
    return result


def collect_redbubble():
    """Redbubble: アップロード状況"""
    sf = ROOT / "saas-dev/projects/redbubble/data/state.json"
    if not sf.exists():
        return {"uploaded": 0, "next_index": 0, "total": 20}
    try:
        s = json.loads(sf.read_text(encoding="utf-8"))
        uploaded = len(s.get("uploaded", []))
        next_idx = s.get("next_quote_index", 0)
        return {"uploaded": uploaded, "next_index": next_idx, "total": 20}
    except Exception:
        return {"uploaded": 0, "next_index": 0, "total": 20}


# ── 集計 ──────────────────────────────────────────────────

NOTE_ACCOUNTS = {1: "takumi_ai_f", 2: "yuuki_nisa", 3: "ken_nenshu_up"}

def build_dashboard_data():
    note_posts          = collect_note()
    note_pdca           = collect_note_pdca()
    room_posts, room_total_override = collect_rakuten_room()
    af_articles         = collect_rakuten_af()
    af_stats            = collect_af_stats(days=30)
    af_pdca             = collect_af_pdca()
    room_pdca           = collect_room_pdca()
    revenue             = collect_revenue()
    kdp_books           = collect_kindle_kdp()
    bots                = collect_investment_bots()
    redbubble           = collect_redbubble()
    gumroad             = collect_gumroad()

    # 直近30日の日付リスト
    today = datetime.now(JST).date()
    dates = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]

    # 日別 note 投稿数
    note_by_date = defaultdict(int)
    for p in note_posts:
        note_by_date[p["date"]] += 1

    # 日別 ROOM 出品数
    room_by_date = {r["date"]: r["count"] for r in room_posts}

    # 日別 AF 記事数
    af_by_date = defaultdict(int)
    for a in af_articles:
        af_by_date[a["date"]] += a["count"]

    # 月別収益
    revenue_by_month = defaultdict(lambda: defaultdict(int))
    for e in revenue:
        month = e["date"][:7]
        source = e.get("source", "その他")
        revenue_by_month[month][source] += e.get("amount", 0)

    this_month = today.isoformat()[:7]
    mtd_revenue = sum(revenue_by_month.get(this_month, {}).values())
    total_revenue = sum(
        sum(v.values()) for v in revenue_by_month.values()
    )

    # ABテスト集計
    ab_stats = defaultdict(lambda: {"A": 0, "B": 0})
    for a in af_articles:
        ab_stats[a["date"]][a.get("strategy", "A")] += a["count"]
    ab_total = {"A": sum(v["A"] for v in ab_stats.values()), "B": sum(v["B"] for v in ab_stats.values())}

    # AF実績データ（日別）
    af_stats_by_date = {s["date"]: s for s in af_stats}
    af_clicks_by_date     = {d: af_stats_by_date[d]["clicks"]     for d in af_stats_by_date}
    af_purchases_by_date  = {d: af_stats_by_date[d]["purchases"]  for d in af_stats_by_date}
    af_cvr_by_date        = {d: af_stats_by_date[d]["cvr"]        for d in af_stats_by_date}
    af_commission_by_date = {d: af_stats_by_date[d]["commission"] for d in af_stats_by_date}

    total_af_clicks    = sum(s["clicks"]     for s in af_stats)
    total_af_purchases = sum(s["purchases"]  for s in af_stats)
    total_af_commission = sum(s["commission"] for s in af_stats)
    avg_cvr = round(total_af_purchases / total_af_clicks * 100, 2) if total_af_clicks > 0 else 0.0

    # 最近の収益エントリ（新しい順10件）
    recent_revenue = sorted(revenue, key=lambda x: x["date"], reverse=True)[:10]

    room_total = room_total_override if room_total_override is not None else sum(r["count"] for r in room_posts)

    # noteアカウント名マッピング
    for p in note_posts:
        p["account_name"] = NOTE_ACCOUNTS.get(p["account"], f"Acct{p['account']}")

    return {
        "generated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M JST"),
        "today": today.isoformat(),
        "dates": dates,
        "mtd_revenue": mtd_revenue,
        "total_revenue": total_revenue,
        "note": {
            "total_posts": len(note_posts),
            "by_date": [note_by_date.get(d, 0) for d in dates],
            "recent": note_posts[-5:][::-1],
            "pdca": note_pdca,
        },
        "rakuten_room": {
            "total_posted": room_total,
            "by_date": [room_by_date.get(d, 0) for d in dates],
            "pdca": room_pdca,
        },
        "af_performance": {
            "total_clicks":     total_af_clicks,
            "total_purchases":  total_af_purchases,
            "total_commission": total_af_commission,
            "avg_cvr":          avg_cvr,
            "clicks_by_date":     [af_clicks_by_date.get(d, 0)     for d in dates],
            "purchases_by_date":  [af_purchases_by_date.get(d, 0)  for d in dates],
            "cvr_by_date":        [af_cvr_by_date.get(d, None)     for d in dates],
            "commission_by_date": [af_commission_by_date.get(d, 0) for d in dates],
            "pdca": af_pdca,
        },
        "rakuten_af": {
            "total_articles": sum(a["count"] for a in af_articles),
            "by_date": [af_by_date.get(d, 0) for d in dates],
            "ab_total": ab_total,
        },
        "revenue": {
            "by_month": {m: dict(v) for m, v in sorted(revenue_by_month.items())},
            "recent": recent_revenue,
        },
        "kindle_kdp": {
            "total_books": len(kdp_books),
            "recent": kdp_books[-5:][::-1],
        },
        "investment_bots": bots,
        "redbubble": redbubble,
        "gumroad": gumroad,
    }


# ── HTML生成 ───────────────────────────────────────────────

def generate_html(data: dict) -> str:
    d = json.dumps(data, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Holdings Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background: #0f1117; color: #e0e0e0; font-family: -apple-system, sans-serif; padding: 24px; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  .subtitle {{ color: #888; font-size: 0.85rem; margin-bottom: 24px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 32px; }}
  .card {{ background: #1e2130; border-radius: 12px; padding: 20px; }}
  .card-label {{ font-size: 0.75rem; color: #888; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 8px; }}
  .card-value {{ font-size: 1.8rem; font-weight: 700; color: #fff; }}
  .card-sub {{ font-size: 0.8rem; color: #666; margin-top: 4px; }}
  .section {{ background: #1e2130; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
  .section h2 {{ font-size: 1rem; margin-bottom: 16px; color: #ccc; }}
  .chart-wrap {{ position: relative; height: 200px; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th {{ text-align: left; color: #666; padding: 6px 8px; border-bottom: 1px solid #2a2d3e; }}
  td {{ padding: 6px 8px; border-bottom: 1px solid #1a1d2e; }}
  td a {{ color: #7c9ff5; text-decoration: none; }}
  .ab-bar {{ display: flex; gap: 8px; align-items: center; margin-top: 8px; }}
  .ab-seg {{ height: 8px; border-radius: 4px; }}
  @media (max-width: 640px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
</style>
</head>
<body>
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px">
  <h1>AI Holdings Dashboard</h1>
  <button id="refresh-btn" onclick="triggerRefresh()" style="background:#2a2d3e;color:#7c9ff5;border:1px solid #7c9ff5;border-radius:8px;padding:8px 18px;cursor:pointer;font-size:0.85rem">今すぐ更新</button>
</div>
<p class="subtitle">生成: {data['generated_at']} &nbsp;｜&nbsp; 毎日 07:00 JST 自動更新</p>
<p id="refresh-msg" style="font-size:0.8rem;margin-bottom:16px;min-height:1.2em"></p>

<div class="cards">
  <div class="card">
    <div class="card-label">今月収益（手動入力）</div>
    <div class="card-value" id="mtd">¥0</div>
    <div class="card-sub">累計: <span id="total">¥0</span></div>
  </div>
  <div class="card">
    <div class="card-label">note 総投稿数</div>
    <div class="card-value" id="note-total">0</div>
    <div class="card-sub">3アカウント合計</div>
  </div>
  <div class="card">
    <div class="card-label">楽天ROOM 総出品数</div>
    <div class="card-value" id="room-total">0</div>
    <div class="card-sub">累計</div>
  </div>
  <div class="card">
    <div class="card-label">楽天AF 総記事数</div>
    <div class="card-value" id="af-total">0</div>
    <div class="card-sub">はてなブログ</div>
  </div>
  <div class="card">
    <div class="card-label">Kindle 出版済み</div>
    <div class="card-value" id="kdp-total">0</div>
    <div class="card-sub">累計冊数</div>
  </div>
  <div class="card">
    <div class="card-label">Redbubble 出品数</div>
    <div class="card-value" id="rb-total">0</div>
    <div class="card-sub" id="rb-sub">残り0件</div>
  </div>
  <div class="card">
    <div class="card-label">Gumroad 月収</div>
    <div class="card-value" id="gm-revenue">$0</div>
    <div class="card-sub" id="gm-progress">目標$2,000の0%</div>
  </div>
</div>

<div class="section" style="margin-bottom:20px">
  <h2>投資ボット ステータス（ペーパートレード）</h2>
  <div id="bot-cards" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:12px"></div>
</div>

<div class="grid2">
  <div class="section">
    <h2>note 投稿数（30日）</h2>
    <div class="chart-wrap"><canvas id="noteChart"></canvas></div>
    <div id="note-pdca-box" style="margin-top:14px;padding:12px;background:#1a1d2e;border-radius:8px;font-size:0.82rem;color:#aaa;display:none">
      <div style="margin-bottom:8px"><span style="color:#7c9ff5;font-weight:600">PDCA洞察:</span> <span id="note-pdca-insight"></span></div>
      <div id="note-pdca-accounts" style="display:flex;flex-direction:column;gap:6px"></div>
    </div>
  </div>
  <div class="section">
    <h2>楽天ROOM 出品数（30日）</h2>
    <div class="chart-wrap"><canvas id="roomChart"></canvas></div>
    <div id="room-pdca-box" style="margin-top:14px;padding:12px;background:#1a1d2e;border-radius:8px;font-size:0.82rem;color:#aaa;display:none">
      <div style="margin-bottom:6px"><span style="color:#f5a623;font-weight:600">ROOM PDCA:</span> <span id="room-pdca-insight"></span></div>
      <div style="display:flex;gap:16px;flex-wrap:wrap">
        <div><span style="color:#888">優先カテゴリ:</span> <span id="room-pdca-cat" style="color:#fff"></span></div>
        <div><span style="color:#888">フック例:</span> <span id="room-pdca-hook" style="color:#7c9ff5"></span></div>
        <div><span style="color:#888">CTA:</span> <span id="room-pdca-cta" style="color:#50e3a4"></span></div>
      </div>
    </div>
  </div>
</div>

<div class="section" style="margin-bottom:20px">
  <h2>楽天AF / ROOM パフォーマンス（30日）</h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:16px">
    <div style="background:#252838;border-radius:10px;padding:14px">
      <div style="font-size:0.7rem;color:#888">クリック合計</div>
      <div style="font-size:1.4rem;font-weight:700;color:#fff" id="af-clicks">-</div>
    </div>
    <div style="background:#252838;border-radius:10px;padding:14px">
      <div style="font-size:0.7rem;color:#888">購入合計</div>
      <div style="font-size:1.4rem;font-weight:700;color:#fff" id="af-purchases">-</div>
    </div>
    <div style="background:#252838;border-radius:10px;padding:14px">
      <div style="font-size:0.7rem;color:#888">平均CVR</div>
      <div style="font-size:1.4rem;font-weight:700;color:#50e3a4" id="af-cvr">-</div>
    </div>
    <div style="background:#252838;border-radius:10px;padding:14px">
      <div style="font-size:0.7rem;color:#888">報酬合計</div>
      <div style="font-size:1.4rem;font-weight:700;color:#f5a623" id="af-commission">-</div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px">
    <div><div style="font-size:0.8rem;color:#aaa;margin-bottom:6px">クリック数（30日）</div><div class="chart-wrap"><canvas id="afClickChart"></canvas></div></div>
    <div><div style="font-size:0.8rem;color:#aaa;margin-bottom:6px">CVR %（30日）</div><div class="chart-wrap"><canvas id="afCvrChart"></canvas></div></div>
    <div><div style="font-size:0.8rem;color:#aaa;margin-bottom:6px">報酬 ¥（30日）</div><div class="chart-wrap"><canvas id="afCommissionChart"></canvas></div></div>
  </div>
  <div id="af-pdca-box" style="margin-top:14px;padding:12px;background:#1a1d2e;border-radius:8px;font-size:0.82rem;color:#aaa;display:none">
    <span style="color:#7c9ff5;font-weight:600">PDCA最新知見:</span> <span id="af-pdca-insight"></span>
    &nbsp;｜&nbsp; <span style="color:#50e3a4">次週注力:</span> <span id="af-pdca-niche"></span>
  </div>
</div>

<div class="grid2">
  <div class="section">
    <h2>楽天AF 記事数（30日）</h2>
    <div class="chart-wrap"><canvas id="afChart"></canvas></div>
  </div>
  <div class="section">
    <h2>収益（月別）</h2>
    <div class="chart-wrap"><canvas id="revenueChart"></canvas></div>
  </div>
</div>

<div class="grid2">
  <div class="section">
    <h2>楽天AF A/Bテスト状況</h2>
    <div id="ab-stats"></div>
  </div>
  <div class="section">
    <h2>最近の収益ログ</h2>
    <table>
      <thead><tr><th>日付</th><th>事業</th><th>金額</th><th>メモ</th></tr></thead>
      <tbody id="rev-table"></tbody>
    </table>
  </div>
</div>

<div class="grid2">
  <div class="section">
    <h2>note 最近の記事</h2>
    <table>
      <thead><tr><th>日付</th><th>アカウント</th><th>タイトル</th><th>価格</th></tr></thead>
      <tbody id="note-table"></tbody>
    </table>
  </div>
  <div class="section">
    <h2>Kindle 出版済み書籍</h2>
    <table>
      <thead><tr><th>日付</th><th>タイトル</th><th>ステータス</th></tr></thead>
      <tbody id="kdp-table"></tbody>
    </table>
  </div>
</div>

<div class="section" style="margin-bottom:20px">
  <h2>Gumroad デジタル商品（月水金 自動出品）</h2>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:16px">
    <div style="background:#252838;border-radius:10px;padding:14px">
      <div style="font-size:0.7rem;color:#888">月収（USD）</div>
      <div style="font-size:1.4rem;font-weight:700;color:#fff" id="gm-rev-card">$0</div>
    </div>
    <div style="background:#252838;border-radius:10px;padding:14px">
      <div style="font-size:0.7rem;color:#888">目標達成率</div>
      <div style="font-size:1.4rem;font-weight:700;color:#50e3a4" id="gm-pct-card">0%</div>
    </div>
    <div style="background:#252838;border-radius:10px;padding:14px">
      <div style="font-size:0.7rem;color:#888">出品中商品数</div>
      <div style="font-size:1.4rem;font-weight:700;color:#fff" id="gm-prods-card">0</div>
    </div>
    <div style="background:#252838;border-radius:10px;padding:14px">
      <div style="font-size:0.7rem;color:#888">目標</div>
      <div style="font-size:1.4rem;font-weight:700;color:#f5a623" id="gm-goal-card">$2,000/月</div>
    </div>
  </div>
  <div style="background:#252838;border-radius:8px;padding:10px 14px;margin-bottom:14px">
    <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#888;margin-bottom:6px">
      <span>進捗</span><span id="gm-bar-label">$0 / $2,000</span>
    </div>
    <div style="background:#1a1d2e;border-radius:4px;height:8px">
      <div id="gm-bar" style="height:8px;border-radius:4px;background:linear-gradient(90deg,#7c9ff5,#50e3a4);width:0%;transition:width 0.8s"></div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;font-size:0.85rem">
    <div>
      <div style="color:#888;margin-bottom:6px">売れ筋ニッチ Top3</div>
      <div id="gm-niches" style="color:#aaa">-</div>
    </div>
    <div>
      <div style="color:#888;margin-bottom:6px">次回生成ターゲット</div>
      <div id="gm-next" style="color:#7c9ff5">-</div>
    </div>
  </div>
</div>

<div class="section">
  <h2>投資ボット 損益サマリー（ペーパートレード）</h2>
  <table>
    <thead><tr><th>ボット</th><th>残高</th><th>損益</th><th>損益率</th><th>ポジション</th><th>最終更新</th></tr></thead>
    <tbody id="bot-table"></tbody>
  </table>
</div>

<script>
const D = {d};

// サマリーカード
document.getElementById('mtd').textContent = '¥' + D.mtd_revenue.toLocaleString();
document.getElementById('total').textContent = '¥' + D.total_revenue.toLocaleString();
document.getElementById('note-total').textContent = D.note.total_posts;
document.getElementById('room-total').textContent = D.rakuten_room.total_posted.toLocaleString();
document.getElementById('af-total').textContent = D.rakuten_af.total_articles;
document.getElementById('kdp-total').textContent = D.kindle_kdp.total_books;
document.getElementById('rb-total').textContent = D.redbubble.next_index + '件';
document.getElementById('rb-sub').textContent = '残り' + (D.redbubble.total - D.redbubble.next_index) + '件 / 全' + D.redbubble.total + '件';

const labels = D.dates.map(d => d.slice(5));
const chartOpts = (color) => ({{
  responsive: true, maintainAspectRatio: false,
  plugins: {{ legend: {{ display: false }} }},
  scales: {{
    x: {{ ticks: {{ color: '#666', maxTicksLimit: 8 }}, grid: {{ color: '#2a2d3e' }} }},
    y: {{ ticks: {{ color: '#666' }}, grid: {{ color: '#2a2d3e' }}, beginAtZero: true }}
  }}
}});

// AF パフォーマンスカード
const afp = D.af_performance;
document.getElementById('af-clicks').textContent     = afp.total_clicks.toLocaleString();
document.getElementById('af-purchases').textContent  = afp.total_purchases.toLocaleString() + '件';
document.getElementById('af-cvr').textContent        = afp.avg_cvr + '%';
document.getElementById('af-commission').textContent = '¥' + afp.total_commission.toLocaleString();

// AF クリックチャート
new Chart(document.getElementById('afClickChart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ data: afp.clicks_by_date, backgroundColor: '#7c9ff5', borderRadius: 2 }}] }},
  options: {{ ...chartOpts('#7c9ff5'), plugins: {{ legend: {{ display: false }} }} }}
}});

// AF CVRチャート（折れ線・nullはスキップ）
new Chart(document.getElementById('afCvrChart'), {{
  type: 'line',
  data: {{ labels, datasets: [{{
    data: afp.cvr_by_date,
    borderColor: '#50e3a4', backgroundColor: 'rgba(80,227,164,0.1)',
    pointRadius: 2, spanGaps: true, tension: 0.3,
  }}] }},
  options: {{ ...chartOpts('#50e3a4'), plugins: {{ legend: {{ display: false }} }} }}
}});

// AF 報酬チャート
new Chart(document.getElementById('afCommissionChart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ data: afp.commission_by_date, backgroundColor: '#f5a623', borderRadius: 2 }}] }},
  options: {{ ...chartOpts('#f5a623'), plugins: {{ legend: {{ display: false }} }} }}
}});

// PDCA最新知見
if (afp.pdca && afp.pdca.overall_insight) {{
  document.getElementById('af-pdca-box').style.display = 'block';
  document.getElementById('af-pdca-insight').textContent = afp.pdca.overall_insight;
  document.getElementById('af-pdca-niche').textContent   = afp.pdca.niche_recommendation || '-';
}}

new Chart(document.getElementById('noteChart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ data: D.note.by_date, backgroundColor: '#7c9ff5', borderRadius: 3 }}] }},
  options: chartOpts('#7c9ff5')
}});

new Chart(document.getElementById('roomChart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ data: D.rakuten_room.by_date, backgroundColor: '#f5a623', borderRadius: 3 }}] }},
  options: chartOpts('#f5a623')
}});

new Chart(document.getElementById('afChart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ data: D.rakuten_af.by_date, backgroundColor: '#50e3a4', borderRadius: 3 }}] }},
  options: chartOpts('#50e3a4')
}});

// 月別収益チャート
const months = Object.keys(D.revenue.by_month);
const sources = [...new Set(months.flatMap(m => Object.keys(D.revenue.by_month[m])))];
const colors = ['#7c9ff5','#f5a623','#50e3a4','#e35050','#c050e3'];
new Chart(document.getElementById('revenueChart'), {{
  type: 'bar',
  data: {{
    labels: months,
    datasets: sources.map((s, i) => ({{
      label: s,
      data: months.map(m => D.revenue.by_month[m][s] || 0),
      backgroundColor: colors[i % colors.length],
      borderRadius: 3,
    }}))
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ labels: {{ color: '#ccc' }} }} }},
    scales: {{
      x: {{ stacked: true, ticks: {{ color: '#666' }}, grid: {{ color: '#2a2d3e' }} }},
      y: {{ stacked: true, ticks: {{ color: '#666' }}, grid: {{ color: '#2a2d3e' }}, beginAtZero: true }}
    }}
  }}
}});

// ABテスト
const ab = D.rakuten_af.ab_total;
const abTotal = ab.A + ab.B || 1;
document.getElementById('ab-stats').innerHTML = `
  <p style="font-size:0.85rem;color:#aaa;margin-bottom:8px">
    A（多ニッチ7日）: <strong style="color:#7c9ff5">${{ab.A}}件</strong> &nbsp;
    B（少ニッチ1日）: <strong style="color:#50e3a4">${{ab.B}}件</strong>
  </p>
  <div class="ab-bar">
    <div class="ab-seg" style="width:${{(ab.A/abTotal*100).toFixed(1)}}%;background:#7c9ff5"></div>
    <div class="ab-seg" style="width:${{(ab.B/abTotal*100).toFixed(1)}}%;background:#50e3a4"></div>
  </div>
  <p style="font-size:0.75rem;color:#666;margin-top:8px">20%以上差がついたら自動切替</p>
`;

// 収益テーブル
document.getElementById('rev-table').innerHTML = D.revenue.recent.length
  ? D.revenue.recent.map(e => `<tr><td>${{e.date}}</td><td>${{e.source}}</td><td>¥${{e.amount.toLocaleString()}}</td><td>${{e.note||''}}</td></tr>`).join('')
  : '<tr><td colspan="4" style="color:#666">まだ記録なし</td></tr>';

// note記事テーブル
document.getElementById('note-table').innerHTML = D.note.recent.length
  ? D.note.recent.map(e => `<tr><td>${{e.date}}</td><td style="color:#7c9ff5">${{e.account_name||'Acct'+e.account}}</td><td><a href="${{e.url}}" target="_blank">${{e.title.slice(0,40)}}...</a></td><td>${{e.price > 0 ? '¥'+e.price : '無料'}}</td></tr>`).join('')
  : '<tr><td colspan="4" style="color:#666">まだ記録なし</td></tr>';

// 投資ボットカード（ヘッダー直下）
document.getElementById('bot-cards').innerHTML = D.investment_bots.length
  ? D.investment_bots.map(b => {{
      const color  = b.pnl >= 0 ? '#50e3a4' : '#e35050';
      const sign   = b.pnl >= 0 ? '+' : '';
      const pos    = b.positions.length ? b.positions.join('/') : 'なし';
      const posCol = b.positions.length ? '#7c9ff5' : '#555';
      const extra = b.name === 'SCALP' && b.trade_count != null
        ? `<div style="font-size:0.7rem;color:#888;margin-top:3px">${{b.trade_count}}T 勝率${{b.win_rate||0}}% v${{b.strategy_version||1}}</div>`
        : '';
      return `<div style="background:#252838;border-radius:10px;padding:14px">
        <div style="font-size:0.7rem;color:#888;letter-spacing:0.08em">${{b.name}}</div>
        <div style="font-size:1.3rem;font-weight:700;color:#fff;margin:4px 0">$${{Math.round(b.balance).toLocaleString()}}</div>
        <div style="font-size:0.8rem;color:${{color}}">${{sign}}${{b.pnl_pct.toFixed(1)}}%</div>
        <div style="font-size:0.75rem;color:${{posCol}};margin-top:4px">${{pos}}</div>
        <div style="font-size:0.7rem;color:#444;margin-top:2px">${{b.last_run || '-'}}</div>
        ${{extra}}
      </div>`;
    }}).join('')
  : '<p style="color:#666">データなし</p>';

// 投資ボットテーブル
document.getElementById('bot-table').innerHTML = D.investment_bots.length
  ? D.investment_bots.map(b => {{
      const color = b.pnl >= 0 ? '#50e3a4' : '#e35050';
      const sign  = b.pnl >= 0 ? '+' : '';
      const posCell = b.name === 'SCALP' && b.trade_count != null
        ? `${{b.positions.join(', ')||'なし'}} <span style="color:#888;font-size:0.75rem">(${{b.trade_count}}T 勝率${{b.win_rate||0}}% v${{b.strategy_version||1}})</span>`
        : (b.positions.join(', ')||'なし');
      return `<tr>
        <td style="font-weight:700">${{b.name}}</td>
        <td>$${{Math.round(b.balance).toLocaleString()}}</td>
        <td style="color:${{color}}">${{sign}}$${{Math.round(b.pnl).toLocaleString()}}</td>
        <td style="color:${{color}}">${{sign}}${{b.pnl_pct.toFixed(1)}}%</td>
        <td style="font-size:0.8rem;color:#aaa">${{posCell}}</td>
        <td style="color:#666">${{b.last_run}}</td>
      </tr>`;
    }}).join('')
  : '<tr><td colspan="6" style="color:#666">データなし</td></tr>';

// 今すぐ更新ボタン
async function triggerRefresh() {{
  const btn = document.getElementById('refresh-btn');
  const msg = document.getElementById('refresh-msg');

  let token = localStorage.getItem('gh_pat');
  if (!token) {{
    token = prompt('GitHub Personal Access Token を入力してください\\n(Settings → Developer settings → Personal access tokens → repo権限)');
    if (!token) return;
    localStorage.setItem('gh_pat', token);
  }}

  btn.disabled = true;
  btn.textContent = '更新中...';
  msg.style.color = '#888';
  msg.textContent = 'GitHub Actions を起動しています...';

  try {{
    const res = await fetch('https://api.github.com/repos/ryuu321/ai-holdings/actions/workflows/dashboard.yml/dispatches', {{
      method: 'POST',
      headers: {{ 'Authorization': 'token ' + token, 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ ref: 'master' }})
    }});
    if (res.status === 204) {{
      msg.style.color = '#50e3a4';
      msg.textContent = '✓ ワークフロー起動完了。1〜2分後にページを再読み込みしてください。';
    }} else if (res.status === 401) {{
      localStorage.removeItem('gh_pat');
      msg.style.color = '#e35050';
      msg.textContent = 'トークンが無効です。再度ボタンを押してトークンを入力し直してください。';
    }} else {{
      msg.style.color = '#e35050';
      msg.textContent = 'エラー: ' + res.status;
    }}
  }} catch(e) {{
    msg.style.color = '#e35050';
    msg.textContent = 'ネットワークエラー: ' + e.message;
  }}

  btn.disabled = false;
  btn.textContent = '今すぐ更新';
}}

// Kindle KDPテーブル
document.getElementById('kdp-table').innerHTML = D.kindle_kdp.recent.length
  ? D.kindle_kdp.recent.map(e => `<tr><td>${{e.published_at.slice(0,10)}}</td><td>${{e.title.slice(0,30)}}</td><td style="color:${{e.status==='published'?'#50e3a4':'#f5a623'}}">${{e.status}}</td></tr>`).join('')
  : '<tr><td colspan="3" style="color:#666">まだ出版なし</td></tr>';

// Gumroad
const gm = D.gumroad;
document.getElementById('gm-revenue').textContent = '$' + gm.monthly_revenue_usd.toFixed(2);
document.getElementById('gm-progress').textContent = '目標$' + gm.goal_usd.toLocaleString() + 'の' + gm.progress_pct + '%';
document.getElementById('gm-rev-card').textContent = '$' + gm.monthly_revenue_usd.toFixed(2);
document.getElementById('gm-pct-card').textContent = gm.progress_pct + '%';
document.getElementById('gm-prods-card').textContent = gm.total_products;
document.getElementById('gm-goal-card').textContent = '$' + gm.goal_usd.toLocaleString() + '/月';
document.getElementById('gm-bar-label').textContent = '$' + gm.monthly_revenue_usd.toFixed(2) + ' / $' + gm.goal_usd.toLocaleString();
document.getElementById('gm-bar').style.width = Math.min(gm.progress_pct, 100) + '%';
document.getElementById('gm-niches').innerHTML = gm.top_niches.length
  ? gm.top_niches.map(([n, r]) => `<div style="margin-bottom:4px"><span style="color:#fff">${{n}}</span> <span style="color:#f5a623;float:right">$${{r.toFixed(2)}}</span></div>`).join('')
  : '<span style="color:#555">まだ売上なし</span>';
document.getElementById('gm-next').innerHTML = gm.next_niches.length
  ? `<div style="margin-bottom:4px">タイプ: <strong style="color:#50e3a4">${{gm.next_type || 'auto'}}</strong></div>` +
    gm.next_niches.map(n => `<div style="color:#aaa;font-size:0.8rem">・${{n}}</div>`).join('')
  : '-';

// note PDCA インサイト
const np = D.note.pdca;
if (np && np.global_insight) {{
  document.getElementById('note-pdca-box').style.display = 'block';
  document.getElementById('note-pdca-insight').textContent = np.global_insight;
  const accs = np.account_strategy || {{}};
  const acctNames = {{'1':'たくみ(AI副業)','2':'ゆうき(節約投資)','3':'けんじ(転職)'}};
  document.getElementById('note-pdca-accounts').innerHTML = Object.entries(accs).map(([id, s]) =>
    `<div style="border-left:2px solid #7c9ff5;padding-left:8px">
      <span style="color:#ccc;font-size:0.8rem">${{acctNames[id]||'Acct'+id}}</span>
      <span style="color:#888;font-size:0.75rem;margin-left:6px">¥${{s.recommended_price}}</span>
      <div style="color:#aaa;margin-top:2px">${{s.focus}}</div>
      <div style="color:#666;font-size:0.75rem;margin-top:2px">候補: ${{(s.next_topics||[]).join(' / ')}}</div>
    </div>`
  ).join('');
}}

// ROOM PDCA インサイト
const rp = D.rakuten_room.pdca;
if (rp && rp.overall_insight) {{
  document.getElementById('room-pdca-box').style.display = 'block';
  document.getElementById('room-pdca-insight').textContent = rp.overall_insight;
  document.getElementById('room-pdca-cat').textContent = rp.priority_category || '';
  document.getElementById('room-pdca-hook').textContent = rp.hook_short || '';
  document.getElementById('room-pdca-cta').textContent = rp.cta_text || '';
}}
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("データ収集中...")
    data = build_dashboard_data()
    html = generate_html(data)
    out = ROOT / "docs/index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"生成完了: {out}")
    print(f"  note投稿: {data['note']['total_posts']}件")
    print(f"  ROOM出品: {data['rakuten_room']['total_posted']}件")
    print(f"  AF記事:   {data['rakuten_af']['total_articles']}件")
    print(f"  今月収益: {data['mtd_revenue']:,}円")
