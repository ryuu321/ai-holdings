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


def _extract_program_name(raw: str) -> str:
    """テーブルセルの全テキストからプログラム名を抽出"""
    m = re.search(r'プログラム名\n(.+?)(?:\n|$)', raw)
    if m:
        name = re.sub(r'[（(]\d{2}-\d{4}[）)]$', '', m.group(1)).strip()
        return name
    # フォールバック: 最初の有意な行
    for line in raw.splitlines():
        line = line.strip()
        if line and line not in ("広告主名", "プログラム名", "対応デバイス", "成果報酬", "EPC", "確定率"):
            return line
    return raw[:50]


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
        # パブリッシャーのログインフォームは www.a8.net/ のトップページに埋め込まれている
        # (pub.a8.net/ はサーバーサイドリダイレクト→www.a8.net/)
        print("[A8] ログイン中... (www.a8.net トップページのフォームを使用)")

        page.goto("https://www.a8.net/", wait_until="networkidle", timeout=30000)
        _save_debug(page, "00_top")
        print(f"[A8] トップページ: {page.url} | {page.title()}")

        # 全フォームを確認してパブリッシャー用フォームを特定
        forms = page.query_selector_all("form")
        print(f"[A8] フォーム数: {len(forms)}")
        for i, form in enumerate(forms):
            try:
                action = form.get_attribute("action") or ""
                inputs_in_form = form.query_selector_all("input")
                print(f"  form[{i}]: action={action!r} inputs={len(inputs_in_form)}")
            except Exception:
                pass

        # 全inputを確認
        all_inputs = page.query_selector_all("input")
        print(f"[A8] 全input数: {len(all_inputs)}")
        for inp in all_inputs:
            try:
                n = inp.get_attribute("name") or ""
                t = inp.get_attribute("type") or ""
                iid = inp.get_attribute("id") or ""
                vis = inp.is_visible()
                print(f"  input name={n!r} type={t!r} id={iid!r} visible={vis}")
            except Exception:
                pass

        # パブリッシャーフォーム（action=pub.a8.net/a8v2/asLoginAction.do）を特定して直接入力
        pub_form = None
        for form in forms:
            try:
                action = form.get_attribute("action") or ""
                if "asLoginAction" in action and "pub.a8.net" in action:
                    pub_form = form
                    print(f"[A8] パブリッシャーフォーム発見: {action}")
                    break
            except Exception:
                pass

        if not pub_form:
            print("[A8] パブリッシャーログインフォームが見つかりません")
            _save_debug(page, "02_no_pub_form")
            browser.close()
            return []

        # フォーム内のフィールドを探して入力
        login_field = pub_form.query_selector('input[name="login"]') or pub_form.query_selector('input[type="text"]')
        pass_field  = pub_form.query_selector('input[name="passwd"]') or pub_form.query_selector('input[type="password"]')
        submit_btn  = pub_form.query_selector('input[type="submit"]') or pub_form.query_selector('button[type="submit"]')

        if not login_field:
            print("[A8] ログインフィールドが見つかりません")
            _save_debug(page, "02_no_login_field")
            browser.close()
            return []
        if not pass_field:
            print("[A8] パスワードフィールドが見つかりません")
            _save_debug(page, "02_no_pass_field")
            browser.close()
            return []

        login_field.fill(A8_EMAIL)
        print(f"[A8] メール入力完了")
        pass_field.fill(A8_PASSWORD)
        print(f"[A8] パスワード入力完了")

        if submit_btn:
            submit_btn.click()
            print(f"[A8] フォームサブミット")
        else:
            # Enterキーでサブミット
            pass_field.press("Enter")
            print(f"[A8] Enterキーでサブミット")

        page.wait_for_load_state("networkidle", timeout=20000)
        _save_debug(page, "02_after_login")
        print(f"[A8] ログイン後URL: {page.url}")

        current_url = page.url
        current_title = page.title()
        print(f"[A8] ログイン後: {current_url} | {current_title}")
        # asLoginAction.do は認証処理URL（リダイレクト途中）なので成功扱いにしない
        # ログイン失敗 = ログインフォームに戻る or エラーページ
        login_failed = (
            ("login" in current_url.lower() and "Action" not in current_url)
            or "ログイン" in current_title
            or "ログインエラー" in current_title
            or ("a8.net" in current_url and "login" in current_url and "pub.a8.net" not in current_url)
        )
        if login_failed:
            print(f"[A8] ログイン失敗")
            _save_debug(page, "02_login_fail")
            browser.close()
            return []
        print(f"[A8] ログイン成功（{current_url[:60]}）")

        # ── 2. 提携済みプログラム一覧 ────────────────────────────
        # ログイン後はpub.a8.netのダッシュボードにいる
        # まずダッシュボードのナビリンクをスキャンして提携プログラム管理URLを探す
        dashboard_url = page.url
        all_nav_links = page.query_selector_all("a[href]")
        print(f"[A8] ダッシュボードリンク数: {len(all_nav_links)}")
        for lk in all_nav_links[:50]:
            try:
                lt = lk.inner_text().strip()
                lh = lk.get_attribute("href") or ""
                if lt:
                    print(f"  [NAV] {lt!r} → {lh}")
            except Exception:
                pass

        # 「参加中プログラム」= 承認済みアフィリエイトプログラムのリスト
        approved_url = None
        for lk in all_nav_links:
            try:
                lt = lk.inner_text().strip()
                lh = lk.get_attribute("href") or ""
                if "参加中" in lt or "partnerProgram" in lh:
                    full = lh if lh.startswith("http") else f"https://pub.a8.net{lh}"
                    print(f"[A8] 参加中プログラムリンク: {lt!r} → {full}")
                    r = page.goto(full, wait_until="networkidle", timeout=20000)
                    if r and r.status < 400 and "見つかりません" not in page.title():
                        approved_url = page.url
                        print(f"[A8] 参加中プログラムページ: {approved_url}")
                        break
            except Exception:
                pass

        if not approved_url:
            # 直接URLで試す
            candidate = "https://pub.a8.net/a8v2/media/partnerProgramListAction.do?act=search&viewPage="
            try:
                r = page.goto(candidate, wait_until="networkidle", timeout=20000)
                print(f"[A8] 直接試行: {page.url} | {page.title()}")
                if r and r.status < 400 and "見つかりません" not in page.title():
                    approved_url = page.url
            except Exception as e:
                print(f"[A8] 直接試行失敗: {e}")

        time.sleep(1)
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
                if any(kw in href for kw in ["sAffiliate", "sProgramDetail", "affiliateId", "programId",
                                             "asAffiliate", "asProgramDetail", "partnerProgram", "programDetail",
                                             "media/program"]):
                    if href not in seen_hrefs and text and len(text) > 1:
                        seen_hrefs.add(href)
                        base = "https://pub.a8.net" if not href.startswith("http") else ""
                        full_href = base + href
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
                full_href = href if href.startswith("http") else f"https://pub.a8.net{href}" if href else ""
                if name_cell and len(name_cell) > 1:
                    row_programs.append({
                        "name": name_cell,
                        "href": full_href,
                        "commission_text": commission_text,
                    })
            except Exception:
                pass

        # 名前クリーンアップ＆フィルタ（クリーン名ベース）
        JUNK_NAMES = {"条件を追加する", "A8セルフバック", "【A8セルフバック】", "成果反映用"}
        cleaned_entries = []
        for entry in (row_programs if row_programs else
                      [{"name": p["name"], "href": p["href"], "commission_text": ""} for p in program_links]):
            clean_name = _extract_program_name(entry["name"])
            if any(junk in clean_name for junk in JUNK_NAMES):
                continue
            entry["clean_name"] = clean_name
            cleaned_entries.append(entry)

        print(f"[A8] プログラム候補: {len(cleaned_entries)}件（全{len(row_programs or program_links)}件中）")

        # ── 4. 各プログラムのリンク素材ページへ遷移してURLを取得 ──
        for i, entry in enumerate(cleaned_entries[:20]):  # 最大20件
            if not entry.get("href"):
                continue
            try:
                clean_name = entry.get("clean_name", entry["name"][:30])
                print(f"  [{i+1}] {clean_name[:40]} → リンク取得中...")
                page.goto(entry["href"], wait_until="networkidle", timeout=20000)
                time.sleep(0.5)

                # 最初の1件だけスクリーンショット保存
                if i == 0:
                    _save_debug(page, "04_link_page_sample")

                # px.a8.net URLを多重手段で取得
                def _get_px_url() -> str:
                    # 1) ページHTML全体
                    html = page.content()
                    found = _extract_a8_url(html)
                    if found:
                        return found
                    # 2) textareaのvalue (JS評価)
                    try:
                        vals = page.evaluate("Array.from(document.querySelectorAll('textarea')).map(t=>t.value)")
                        for v in vals:
                            found = _extract_a8_url(str(v))
                            if found:
                                return found
                    except Exception:
                        pass
                    # 3) input[value*=px.a8.net]
                    for inp in page.query_selector_all("input"):
                        try:
                            v = inp.get_attribute("value") or ""
                            found = _extract_a8_url(v)
                            if found:
                                return found
                        except Exception:
                            pass
                    # 4) a[href*=px.a8.net]
                    for anc in page.query_selector_all("a[href]"):
                        try:
                            h = anc.get_attribute("href") or ""
                            if "px.a8.net" in h:
                                return h.rstrip('.,;')
                        except Exception:
                            pass
                    return ""

                affiliate_url = _get_px_url()

                # まだ見つからなければ テキストリンク系のリンクを経由
                if not affiliate_url:
                    for sel in [
                        "a:has-text('テキストリンク')",
                        "a:has-text('リンク素材')",
                        "a:has-text('リンクコード')",
                        "a[href*='textLink']",
                        "a[href*='linkCode']",
                    ]:
                        try:
                            el = page.query_selector(sel)
                            if el:
                                mat_href = el.get_attribute("href") or ""
                                mat_full = mat_href if mat_href.startswith("http") else f"https://pub.a8.net{mat_href}"
                                page.goto(mat_full, wait_until="networkidle", timeout=15000)
                                time.sleep(0.5)
                                affiliate_url = _get_px_url()
                                if affiliate_url:
                                    break
                        except Exception:
                            pass

                # 報酬テキストを既存データから使用
                commission_text = entry.get("commission_text", "")
                commission_value = _parse_commission(commission_text)

                programs.append({
                    "name":             clean_name,
                    "url":              affiliate_url,
                    "commission_text":  commission_text,
                    "commission_value": commission_value,
                    "detail_url":       entry["href"],
                })
                status = f"✓ {affiliate_url[:60]}..." if affiliate_url else "×URL未取得"
                print(f"     {status} | 報酬: {commission_value}円")

            except Exception as e:
                print(f"  [{i+1}] エラー: {e}")
                programs.append({
                    "name":             entry.get("clean_name", entry["name"][:50]),
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
