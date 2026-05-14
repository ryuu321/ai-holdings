"""
a8_scraper.py — A8.netから承認済みアフィリエイトリンクを完全自動取得
各プログラムのリンク素材ページまで遷移してpx.a8.netのURLを取得する
"""
import os
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR       = Path(__file__).parent / "data"
AFFILIATE_FILE = DATA_DIR / "affiliate_links.json"
DEBUG_DIR      = DATA_DIR / "a8_debug"

A8_EMAIL    = os.environ.get("A8_EMAIL", "")
A8_PASSWORD = os.environ.get("A8_PASSWORD", "")

# アカウントテーマ別マッチキーワード
ACCOUNT_KEYWORDS = {
    1: ["AI", "SaaS", "副業", "学習", "スキル", "オンライン", "フリーランス",
        "動画", "講座", "Udemy", "クラウド", "ソフトウェア", "ツール", "アプリ"],
    2: ["証券", "FX", "投資", "資産", "節税", "クレジット", "カード", "保険",
        "銀行", "ローン", "NISA", "iDeCo", "不動産", "ファンド", "金融"],
    3: ["転職", "求人", "採用", "就職", "キャリア", "派遣", "エージェント",
        "スカウト", "年収", "求職", "仕事", "リクルート", "人材"],
}


def _parse_commission(text: str) -> int:
    """報酬テキストから最大値（円）を返す"""
    text = text.replace(",", "").replace("，", "").replace("、", "")
    nums = [int(m) for m in re.findall(r'\d+', text) if int(m) >= 100]
    return max(nums) if nums else 0


def _save_debug(page, name: str):
    """デバッグ用スクリーンショットを保存"""
    try:
        DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = DEBUG_DIR / f"{name}.png"
        page.screenshot(path=str(path))
        print(f"  [DEBUG] スクリーンショット保存: {path.name}")
    except Exception:
        pass


def _extract_a8_url(text: str) -> str:
    """テキストからpx.a8.netのURLを抽出"""
    m = re.search(r'https?://px\.a8\.net/[^\s\'"<>\)]+', text)
    return m.group(0).rstrip('.,;') if m else ""


def scrape_a8_approved() -> list[dict]:
    """
    A8.netにログインし、承認済みプログラムのアフィリリンクを取得する。
    各プログラムのリンク素材ページまで遷移してpx.a8.netのURLを抽出。
    """
    if not A8_EMAIL or not A8_PASSWORD:
        print("[A8] A8_EMAIL / A8_PASSWORD が未設定")
        return []

    from playwright.sync_api import sync_playwright

    programs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        # ── 1. ログイン ──────────────────────────────────────────
        print("[A8] ログイン中...")
        page.goto("https://www.a8.net/a8v2/login.html", wait_until="networkidle", timeout=30000)
        _save_debug(page, "01_login")

        # JS描画を待ってからinputを列挙
        print(f"[A8] ページURL: {page.url}")
        print(f"[A8] ページタイトル: {page.title()}")
        try:
            page.wait_for_selector("input", timeout=15000)
        except Exception:
            print("[A8] input要素がタイムアウトまでに現れませんでした")
            # HTMLソースをダンプして原因確認
            html = page.content()
            (DEBUG_DIR / "login_page.html").write_text(html[:5000], encoding="utf-8")
            _save_debug(page, "01b_no_input")
            browser.close()
            return []
        inputs = page.query_selector_all("input")
        print(f"[A8] input要素数: {len(inputs)}")
        for inp in inputs:
            try:
                n = inp.get_attribute("name") or ""
                t = inp.get_attribute("type") or ""
                i = inp.get_attribute("id") or ""
                print(f"  input name={n!r} type={t!r} id={i!r}")
            except Exception:
                pass

        # フォームフィールドを動的に特定
        # 候補セレクタをリストで試す
        email_selectors = [
            'input[name="login_id"]',
            'input[name="mail"]',
            'input[name="email"]',
            'input[name="userId"]',
            'input[name="user_id"]',
            'input[id="login_id"]',
            'input[id="mail"]',
            'input[type="email"]',
        ]
        pass_selectors = [
            'input[name="login_pass"]',
            'input[name="password"]',
            'input[name="passwd"]',
            'input[name="pass"]',
            'input[id="login_pass"]',
            'input[id="password"]',
            'input[type="password"]',
        ]

        def try_fill(selectors, value, label):
            for sel in selectors:
                try:
                    el = page.query_selector(sel)
                    if el and el.is_visible():
                        el.fill(value)
                        print(f"[A8] {label} フィールド: {sel}")
                        return True
                except Exception:
                    pass
            print(f"[A8] {label} フィールドが見つかりません")
            return False

        if not try_fill(email_selectors, A8_EMAIL, "メール"):
            _save_debug(page, "02_login_fail_email")
            browser.close()
            return []
        if not try_fill(pass_selectors, A8_PASSWORD, "パスワード"):
            _save_debug(page, "02_login_fail_pass")
            browser.close()
            return []

        # サブミット
        submitted = False
        for submit_sel in ['input[type="submit"]', 'button[type="submit"]',
                           'button:has-text("ログイン")', 'input[value*="ログイン"]']:
            try:
                el = page.query_selector(submit_sel)
                if el and el.is_visible():
                    el.click()
                    submitted = True
                    print(f"[A8] サブミット: {submit_sel}")
                    break
            except Exception:
                pass
        if not submitted:
            print("[A8] サブミットボタンが見つかりません")
            _save_debug(page, "02_no_submit")
            browser.close()
            return []

        page.wait_for_load_state("networkidle", timeout=20000)
        _save_debug(page, "02_after_login")
        print(f"[A8] ログイン後URL: {page.url}")

        if "login" in page.url.lower() or "ログイン" in page.title():
            print(f"[A8] ログイン失敗 (URL: {page.url})")
            browser.close()
            return []
        print(f"[A8] ログイン成功")

        # ── 2. 提携済みプログラム一覧 ────────────────────────────
        # status=2 が「提携中」、status=1 が「申請中」
        approved_url = "https://www.a8.net/a8v2/sMediaAffiliate.do?action=index&affiliateStatus=2"
        page.goto(approved_url, wait_until="networkidle", timeout=30000)
        time.sleep(2)
        _save_debug(page, "03_approved_list")
        print(f"[A8] 提携済み一覧: {page.url}")

        # ── 3. プログラム行を収集 ────────────────────────────────
        # A8.netのテーブル構造をページテキストで把握してからパース
        page_text = page.inner_text("body")
        total_text_len = len(page_text)
        print(f"[A8] ページテキスト長: {total_text_len}字")

        # プログラムへのリンクを収集
        all_links = page.query_selector_all("a[href]")
        program_links = []
        seen_hrefs = set()
        for link in all_links:
            try:
                href = link.get_attribute("href") or ""
                text = link.inner_text().strip()
                # A8.netのプログラム詳細リンクパターン
                if any(kw in href for kw in ["sAffiliate", "sProgramDetail", "affiliateId", "programId"]):
                    if href not in seen_hrefs and text and len(text) > 1:
                        seen_hrefs.add(href)
                        full_href = href if href.startswith("http") else f"https://www.a8.net{href}"
                        program_links.append({"name": text, "href": full_href})
            except Exception:
                pass

        # テーブル行からもプログラム名を抽出
        rows = page.query_selector_all("table tr")
        row_programs = []
        for row in rows:
            try:
                cells = row.query_selector_all("td")
                if len(cells) < 2:
                    continue
                name_cell = cells[0].inner_text().strip()
                # 報酬セルを探す（数字+円が含まれるセル）
                commission_text = ""
                for cell in cells:
                    ct = cell.inner_text().strip()
                    if re.search(r'\d+円|\d+%', ct):
                        commission_text = ct
                        break
                # リンク
                link_el = row.query_selector("a[href]")
                href = link_el.get_attribute("href") if link_el else ""
                full_href = href if href.startswith("http") else f"https://www.a8.net{href}" if href else ""
                if name_cell and len(name_cell) > 1:
                    row_programs.append({
                        "name": name_cell,
                        "href": full_href,
                        "commission_text": commission_text,
                    })
            except Exception:
                pass

        # マージ
        all_program_entries = row_programs if row_programs else [
            {"name": p["name"], "href": p["href"], "commission_text": ""} for p in program_links
        ]
        print(f"[A8] プログラム候補: {len(all_program_entries)}件")

        # ── 4. 各プログラムのリンク素材ページへ遷移してURLを取得 ──
        for i, entry in enumerate(all_program_entries[:30]):  # 最大30件
            if not entry.get("href"):
                continue
            try:
                print(f"  [{i+1}] {entry['name'][:30]} → リンク取得中...")
                page.goto(entry["href"], wait_until="networkidle", timeout=20000)
                time.sleep(1)

                # リンク素材ページへのリンクを探す
                material_link = page.query_selector(
                    "a:has-text('リンク素材'), a:has-text('広告素材'), "
                    "a:has-text('テキストリンク'), a[href*='material'], a[href*='link']"
                )
                if material_link:
                    mat_href = material_link.get_attribute("href") or ""
                    mat_full = mat_href if mat_href.startswith("http") else f"https://www.a8.net{mat_href}"
                    page.goto(mat_full, wait_until="networkidle", timeout=20000)
                    time.sleep(1)

                # px.a8.net URLを全ページから検索
                page_html = page.content()
                affiliate_url = _extract_a8_url(page_html)

                # inputフィールドのvalue属性も確認
                if not affiliate_url:
                    inputs = page.query_selector_all("input[value*='px.a8.net'], textarea")
                    for inp in inputs:
                        val = inp.get_attribute("value") or inp.inner_text()
                        found = _extract_a8_url(val)
                        if found:
                            affiliate_url = found
                            break

                # 報酬テキストを取得
                commission_text = entry.get("commission_text", "")
                if not commission_text:
                    # ページから報酬情報を探す
                    body_text = page.inner_text("body")
                    m = re.search(r'(?:報酬|成果報酬|単価)[^\n]{0,50}[\d,]+円', body_text)
                    if m:
                        commission_text = m.group().strip()

                commission_value = _parse_commission(commission_text)

                programs.append({
                    "name":             entry["name"],
                    "url":              affiliate_url,
                    "commission_text":  commission_text,
                    "commission_value": commission_value,
                    "detail_url":       entry["href"],
                })
                status = f"✓ {affiliate_url[:50]}..." if affiliate_url else "URL未取得"
                print(f"     {status} | 報酬: {commission_text or '不明'}")

            except Exception as e:
                print(f"  [{i+1}] エラー: {e}")
                programs.append({
                    "name":             entry["name"],
                    "url":              "",
                    "commission_text":  entry.get("commission_text", ""),
                    "commission_value": _parse_commission(entry.get("commission_text", "")),
                    "detail_url":       entry.get("href", ""),
                })

        browser.close()

    print(f"\n[A8] 取得完了: {len(programs)}件 (URL取得済: {sum(1 for p in programs if p['url'])}件)")
    return programs


def select_best_by_account(programs: list[dict]) -> dict[int, list[dict]]:
    """アカウント別に最高報酬の案件をトップ3選出"""
    # URLが取れているものを優先、なければ報酬値で並べる
    url_ok = [p for p in programs if p.get("url")]
    no_url = [p for p in programs if not p.get("url")]

    result = {}
    for acc_id, keywords in ACCOUNT_KEYWORDS.items():
        matched = []
        for pool in [url_ok, no_url]:  # URLありを優先
            for p in pool:
                name_lower = p["name"].lower()
                if any(kw.lower() in name_lower for kw in keywords):
                    if p not in matched:
                        matched.append(p)

        matched.sort(key=lambda x: (bool(x.get("url")), x["commission_value"]), reverse=True)
        result[acc_id] = matched[:3]

        print(f"\n[A8] アカウント{acc_id} トップ案件:")
        for p in result[acc_id]:
            url_status = "✓URL" if p.get("url") else "×URL未取得"
            print(f"  {p['name'][:35]} | {p['commission_text'] or '報酬不明'} | {url_status}")

    return result


def run():
    print("=" * 50)
    print("A8.net アフィリエイトリンク自動取得")
    print("=" * 50)

    programs = scrape_a8_approved()

    if not programs:
        print("[A8] プログラム取得できず。既存データを維持します。")
        return

    best = select_best_by_account(programs)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "updated_at":   datetime.now(timezone.utc).isoformat(),
        "total_found":  len(programs),
        "url_retrieved": sum(1 for p in programs if p.get("url")),
        "by_account":   {str(k): v for k, v in best.items()},
        "all_programs": sorted(programs, key=lambda x: x["commission_value"], reverse=True),
    }
    AFFILIATE_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[A8] 保存完了: {AFFILIATE_FILE}")


if __name__ == "__main__":
    run()
