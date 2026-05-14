"""
a8_scraper.py — A8.netから承認済みアフィリエイトプログラムを取得
報酬の高い順に選別してaffiliate_links.jsonに保存する
"""
import os
import json
import re
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
AFFILIATE_FILE = DATA_DIR / "affiliate_links.json"

A8_EMAIL    = os.environ.get("A8_EMAIL", "")
A8_PASSWORD = os.environ.get("A8_PASSWORD", "")

# アカウントテーマ → 案件マッチングキーワード
ACCOUNT_KEYWORDS = {
    1: ["AI", "SaaS", "副業", "学習", "スキル", "オンライン", "フリーランス", "クラウド", "動画", "講座", "Udemy", "転職支援"],
    2: ["証券", "FX", "投資", "資産", "節税", "クレジット", "カード", "保険", "銀行", "ローン", "NISA", "iDeCo", "不動産"],
    3: ["転職", "求人", "採用", "就職", "キャリア", "派遣", "エージェント", "スカウト", "年収", "求職"],
}

# 報酬テキストから数値を抽出するパターン
def _parse_commission(text: str) -> int:
    """報酬テキストから最大値を整数で返す（¥換算）"""
    text = text.replace(",", "").replace("，", "")
    # 「最大〇〇円」「〇〇円/件」「〇〇%」などに対応
    numbers = [int(m) for m in re.findall(r'\d+', text) if int(m) >= 100]
    if not numbers:
        return 0
    return max(numbers)


def scrape_a8_approved() -> list[dict]:
    """A8.netにログインして提携済みプログラムを取得する"""
    if not A8_EMAIL or not A8_PASSWORD:
        print("[A8] A8_EMAIL / A8_PASSWORD が未設定")
        return []

    from playwright.sync_api import sync_playwright

    programs = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # ── ログイン ──
            print("[A8] ログイン中...")
            page.goto("https://www.a8.net/a8v2/login.html", wait_until="networkidle", timeout=30000)
            page.fill('input[name="login_id"], input[id="login_id"], input[type="email"]', A8_EMAIL)
            page.fill('input[name="password"], input[id="password"], input[type="password"]', A8_PASSWORD)
            page.click('input[type="submit"], button[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=20000)

            if "login" in page.url.lower() or "ログイン" in page.title():
                print("[A8] ログイン失敗 — メールアドレス/パスワードを確認してください")
                browser.close()
                return []
            print(f"[A8] ログイン成功: {page.url}")

            # ── 提携済みプログラム一覧ページ ──
            page.goto("https://www.a8.net/a8v2/sMediaAffiliate.do?action=index", wait_until="networkidle", timeout=30000)
            time.sleep(2)

            # 全ページを取得（ページネーション対応）
            page_num = 1
            while True:
                print(f"[A8] ページ {page_num} を取得中...")
                rows = page.query_selector_all("table tr, .program-item, [class*='affiliate-row'], [class*='program-row']")

                found_in_page = 0
                for row in rows:
                    try:
                        text = row.inner_text()
                        if not text.strip() or len(text) < 10:
                            continue

                        # 案件名
                        name_el = row.query_selector("a, [class*='name'], [class*='title'], td:first-child")
                        name = name_el.inner_text().strip() if name_el else text.split("\n")[0].strip()
                        if not name or len(name) < 2:
                            continue

                        # アフィリリンク（href から取得）
                        link_el = row.query_selector("a[href*='px.a8.net'], a[href*='a8.net']")
                        url = link_el.get_attribute("href") if link_el else ""

                        # リンク取得ページに遷移して取得する場合の対処
                        if not url:
                            detail_el = row.query_selector("a")
                            detail_href = detail_el.get_attribute("href") if detail_el else ""
                            if detail_href and "sMediaAffiliate" in detail_href:
                                url = f"__pending__{detail_href}"

                        # 報酬テキスト
                        commission_text = ""
                        for sel in ["[class*='reward'], [class*='commission'], [class*='fee'], td:nth-child(3), td:nth-child(4)"]:
                            try:
                                el = row.query_selector(sel)
                                if el:
                                    commission_text = el.inner_text().strip()
                                    break
                            except Exception:
                                pass
                        if not commission_text:
                            # テキスト全体から報酬っぽい部分を抽出
                            m = re.search(r'(?:報酬|成果|単価|円)[^\n]*[\d,]+円', text)
                            if m:
                                commission_text = m.group()

                        commission_value = _parse_commission(commission_text)

                        programs.append({
                            "name": name,
                            "url": url,
                            "commission_text": commission_text,
                            "commission_value": commission_value,
                        })
                        found_in_page += 1
                    except Exception:
                        pass

                print(f"[A8] ページ {page_num}: {found_in_page}件取得")

                # 次ページへ
                next_btn = page.query_selector("a:has-text('次へ'), a:has-text('次ページ'), [class*='next']:not([disabled])")
                if next_btn and page_num < 20:
                    next_btn.click()
                    page.wait_for_load_state("networkidle", timeout=15000)
                    page_num += 1
                else:
                    break

            browser.close()

    except Exception as e:
        print(f"[A8] スクレイピングエラー: {e}")

    print(f"[A8] 合計 {len(programs)} 件取得")
    return programs


def select_best_by_account(programs: list[dict]) -> dict:
    """
    各アカウント（1=AI副業, 2=投資, 3=転職）ごとに
    キーワードマッチ×報酬の高い順でトップ3を選ぶ
    """
    result = {1: [], 2: [], 3: []}

    for acc_id, keywords in ACCOUNT_KEYWORDS.items():
        matched = []
        for p in programs:
            name_lower = p["name"].lower()
            if any(kw.lower() in name_lower for kw in keywords):
                matched.append(p)

        # 報酬の高い順にソートしてトップ3
        matched.sort(key=lambda x: x["commission_value"], reverse=True)
        result[acc_id] = matched[:3]
        print(f"[A8] アカウント{acc_id}: {[p['name'] for p in result[acc_id]]}")

    return result


def run():
    print("=== A8.net アフィリエイトリンク取得 ===")
    programs = scrape_a8_approved()

    if not programs:
        print("[A8] プログラム取得できず。既存データを維持します。")
        return

    best = select_best_by_account(programs)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    AFFILIATE_FILE.write_text(
        json.dumps({"updated_at": __import__("datetime").datetime.utcnow().isoformat(),
                    "by_account": {str(k): v for k, v in best.items()},
                    "all_programs": sorted(programs, key=lambda x: x["commission_value"], reverse=True)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[A8] 保存完了: {AFFILIATE_FILE}")

    # サマリー表示
    for acc_id, progs in best.items():
        print(f"\n  アカウント{acc_id}:")
        for p in progs:
            print(f"    {p['name']} — {p['commission_text'] or '報酬不明'}")


if __name__ == "__main__":
    run()
