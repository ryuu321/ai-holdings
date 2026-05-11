"""楽天アフィリエイト レポートスクレイパー（Playwright）"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

SESSION_FILE = Path(__file__).parent.parent / "data" / "af_session.json"
STATS_FILE   = Path(__file__).parent.parent / "data" / "af_stats.json"
JST          = timezone(timedelta(hours=9))
LOGIN_URL    = "https://affiliate.rakuten.co.jp/"
REPORT_URL   = "https://affiliate.rakuten.co.jp/tools/report/"

log = logging.getLogger(__name__)


def scrape_af_stats(days: int = 30) -> list[dict]:
    """楽天AFコンソールから日別レポートを取得。"""
    if not SESSION_FILE.exists():
        log.error("セッションなし。python af_scraper.py --setup を実行してください")
        return []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(SESSION_FILE))
        page    = context.new_page()
        try:
            page.goto(REPORT_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)

            if "login" in page.url or "sign_in" in page.url or "member.rakuten" in page.url:
                log.error("セッション切れ。--setup で再ログインしてください")
                return []

            end_date   = datetime.now(JST)
            start_date = end_date - timedelta(days=days)

            # 期間開始日
            for sel in ["input[name='start_date']", "input[id*='start']", "[placeholder*='開始']", "input[name='from']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.fill(start_date.strftime("%Y/%m/%d"))
                    break

            # 期間終了日
            for sel in ["input[name='end_date']", "input[id*='end']", "[placeholder*='終了']", "input[name='to']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.fill(end_date.strftime("%Y/%m/%d"))
                    break

            # 検索ボタン
            for sel in ["button:has-text('表示')", "button:has-text('検索')", "input[type='submit']", "button[type='submit']"]:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    loc.click()
                    page.wait_for_timeout(3000)
                    break

            stats = _parse_report_table(page)

            context.storage_state(path=str(SESSION_FILE))
            log.info(f"AF stats取得: {len(stats)}日分")
            return sorted(stats, key=lambda x: x["date"])

        except Exception as e:
            log.error(f"スクレイプエラー: {e}")
            try:
                page.screenshot(path=str(SESSION_FILE.parent / "af_scrape_error.png"))
            except Exception:
                pass
            return []
        finally:
            browser.close()


def _parse_report_table(page) -> list[dict]:
    """レポートテーブルをパース。Rakuten AFのレイアウト変化に対応。"""
    stats = []
    rows = page.locator("table tr").all()
    if not rows:
        # テーブルがない場合は空
        log.warning("テーブルが見つかりません")
        return []

    # ヘッダー行を読んで列インデックスを特定
    header_cells = rows[0].locator("th, td").all()
    headers = [c.inner_text().strip() for c in header_cells]
    log.info(f"ヘッダー: {headers}")

    col_date  = _find_col(headers, ["日付", "date", "日"])
    col_click = _find_col(headers, ["クリック", "click", "PV"])
    col_cv    = _find_col(headers, ["購入", "CV", "成果", "件数"])
    col_comm  = _find_col(headers, ["報酬", "commission", "金額", "合計"])

    if col_date is None or col_click is None:
        log.warning(f"列が特定できません。headers={headers}")
        return []

    for row in rows[1:]:
        cells = row.locator("td").all()
        if len(cells) <= max(filter(lambda x: x is not None, [col_date, col_click, col_cv, col_comm])):
            continue
        try:
            raw_date  = cells[col_date].inner_text().strip()
            clicks    = _parse_int(cells[col_click].inner_text())
            purchases = _parse_int(cells[col_cv].inner_text()) if col_cv is not None else 0
            commission = _parse_int(cells[col_comm].inner_text()) if col_comm is not None else 0
            cvr = round(purchases / clicks * 100, 2) if clicks > 0 else 0.0

            # YYYY/MM/DD → YYYY-MM-DD
            date_norm = _normalize_date(raw_date)
            if not date_norm:
                continue

            stats.append({
                "date":       date_norm,
                "clicks":     clicks,
                "purchases":  purchases,
                "cvr":        cvr,
                "commission": commission,
            })
        except (IndexError, ValueError):
            continue

    return stats


def _find_col(headers: list[str], candidates: list[str]) -> int | None:
    for i, h in enumerate(headers):
        for c in candidates:
            if c.lower() in h.lower():
                return i
    return None


def _parse_int(text: str) -> int:
    cleaned = text.replace(",", "").replace("¥", "").replace("円", "").replace(" ", "").strip()
    try:
        return int(float(cleaned))
    except ValueError:
        return 0


def _normalize_date(raw: str) -> str | None:
    for fmt in ["%Y/%m/%d", "%Y-%m-%d", "%Y年%m月%d日", "%m/%d/%Y"]:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def save_stats(stats: list[dict]):
    """既存データとマージして最新90日分を保存。"""
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if STATS_FILE.exists():
        try:
            for s in json.loads(STATS_FILE.read_text(encoding="utf-8")):
                existing[s["date"]] = s
        except Exception:
            pass
    for s in stats:
        existing[s["date"]] = s
    all_stats = sorted(existing.values(), key=lambda x: x["date"])[-90:]
    STATS_FILE.write_text(json.dumps(all_stats, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"AF stats保存完了: {len(all_stats)}日分")


def load_stats(days: int = 30) -> list[dict]:
    if not STATS_FILE.exists():
        return []
    try:
        all_stats = json.loads(STATS_FILE.read_text(encoding="utf-8"))
        cutoff = (datetime.now(JST) - timedelta(days=days)).strftime("%Y-%m-%d")
        return [s for s in all_stats if s["date"] >= cutoff]
    except Exception:
        return []


def setup_session():
    """実際のEdgeプロファイルを使ってセッションを取得。Edgeを完全に閉じてから実行すること。"""
    import os
    edge_profile = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")

    with sync_playwright() as p:
        print("実際のEdgeプロファイルで起動します（Edgeを先に完全に閉じてください）。")
        context = p.chromium.launch_persistent_context(
            user_data_dir=edge_profile,
            channel="msedge",
            headless=False,
        )
        page = context.new_page()
        page.goto(LOGIN_URL)
        print("\n楽天アフィリエイトが開きました。")
        print("ログイン済みであればそのまま Enter を、未ログインならログインしてから Enter を押してください。")
        input(">>> Enter: ")
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_FILE))
        print("セッション保存完了。")
        context.close()


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="[af_scraper] %(asctime)s %(message)s")
    if "--setup" in sys.argv:
        setup_session()
    else:
        stats = scrape_af_stats(days=30)
        if stats:
            save_stats(stats)
            for s in stats[-7:]:
                print(f"  {s['date']}: クリック{s['clicks']} 購入{s['purchases']} CVR{s['cvr']}% 報酬¥{s['commission']}")
        else:
            print("データ取得失敗（セッションがない or レイアウト変更）")
