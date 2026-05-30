"""
gyosei.or.jp 行政書士会会員検索からリード収集
Playwright (Chromium) を使用 → GitHub Actions で実行してください

  pip install playwright && playwright install chromium --with-deps
  python fetch_gyosei_leads.py [--limit 100] [--prefs 13,27,14,23]

出力: leads.csv (company_name, email, url, phone, address, scraped_at)
"""
import argparse
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_DIR = Path(__file__).parent
LEADS_FILE = _DIR / "leads.csv"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "google", "gyosei.or.jp",
              "w3.org", "schema.org", "test@"]

# 都道府県名リスト（検索フォームのselectに合わせる）
PREFS_MAP = {
    1: "北海道", 4: "宮城県", 11: "埼玉県", 12: "千葉県", 13: "東京都",
    14: "神奈川県", 22: "静岡県", 23: "愛知県", 26: "京都府", 27: "大阪府",
    28: "兵庫県", 34: "広島県", 40: "福岡県",
}
DEFAULT_PREF_CODES = [13, 27, 14, 23, 11, 12, 1, 28, 40, 26, 34, 4, 22]

SEARCH_URL = "https://www.gyosei.or.jp/search/"


def _emails_from_html(html: str) -> list[str]:
    found = EMAIL_RE.findall(html)
    result = []
    for e in found:
        e = e.lower().rstrip(".")
        if any(s in e for s in EMAIL_SKIP):
            continue
        if e.split(".")[-1].lower() in {"png", "jpg", "gif", "svg", "pdf", "js", "css"}:
            continue
        if e not in result:
            result.append(e)
    return result[:2]


def load_existing() -> set[str]:
    if not LEADS_FILE.exists():
        return set()
    with open(LEADS_FILE, encoding="utf-8", newline="") as f:
        return {row.get("email", "") for row in csv.DictReader(f) if row.get("email")}


def main():
    parser = argparse.ArgumentParser(description="gyosei.or.jp行政書士会員リード収集")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--prefs", type=str, default="",
                        help="カンマ区切り都道府県コード (例: 13,27,14)")
    parser.add_argument("--headless", action="store_true", default=True)
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        print("Playwright未インストール: pip install playwright && playwright install chromium --with-deps")
        sys.exit(1)

    pref_codes = [int(p) for p in args.prefs.split(",") if p.strip()] if args.prefs else DEFAULT_PREF_CODES
    limit = args.limit

    existing = load_existing()
    print(f"既存リード: {len(existing)}件")

    write_header = not LEADS_FILE.exists()
    found = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = context.new_page()

        with open(LEADS_FILE, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f, fieldnames=["company_name", "email", "url", "phone", "address", "scraped_at"]
            )
            if write_header:
                writer.writeheader()

            for pref_code in pref_codes:
                if found >= limit:
                    break
                pref_name = PREFS_MAP.get(pref_code, str(pref_code))
                print(f"\n[{pref_name}] 検索中...")

                try:
                    page.goto(SEARCH_URL, timeout=30000)
                    page.wait_for_load_state("networkidle", timeout=15000)

                    # 利用規約チェックボックスにチェック
                    try:
                        page.check("input[name='field_kiyaku_value']", timeout=5000)
                    except PWTimeout:
                        try:
                            page.check("input[type='checkbox']", timeout=3000)
                        except PWTimeout:
                            pass

                    # 都道府県選択
                    try:
                        page.select_option("select[name='field_address_pref_code']",
                                           label=pref_name, timeout=5000)
                    except PWTimeout:
                        try:
                            page.select_option("select", label=pref_name, timeout=3000)
                        except PWTimeout:
                            print(f"  都道府県選択失敗: {pref_name}")
                            continue

                    # 検索実行
                    page.click("input[type='submit'], button[type='submit']", timeout=5000)
                    page.wait_for_load_state("networkidle", timeout=20000)
                    time.sleep(2)

                    # 結果ページをパース（複数ページ対応）
                    current_page = 1
                    while found < limit:
                        html = page.content()
                        # 事務所名・電話・リンクを抽出
                        offices = _parse_results(html)
                        print(f"  [P{current_page}] {len(offices)}件")

                        if not offices:
                            break

                        for office in offices:
                            if found >= limit:
                                break

                            name = office.get("name", "")
                            phone = office.get("phone", "")
                            address = office.get("address", "")
                            detail_url = office.get("url", "")

                            email = ""
                            site_url = ""

                            # 詳細ページを開いてウェブサイトURL + メール取得
                            if detail_url:
                                try:
                                    detail_page = context.new_page()
                                    detail_page.goto(detail_url, timeout=20000)
                                    detail_page.wait_for_load_state("networkidle", timeout=10000)
                                    detail_html = detail_page.content()
                                    detail_page.close()

                                    # ホームページURL
                                    hp_m = re.search(
                                        r'href="(https?://(?!www\.gyosei\.or\.jp)[^"]+)"',
                                        detail_html
                                    )
                                    if hp_m:
                                        site_url = hp_m.group(1)

                                    emails = _emails_from_html(detail_html)
                                    if emails:
                                        email = emails[0]
                                    time.sleep(0.5)
                                except Exception as e:
                                    print(f"  detail error: {e}")

                            # 詳細ページにメールがなければウェブサイトを試す
                            if not email and site_url:
                                try:
                                    site_page = context.new_page()
                                    site_page.goto(site_url, timeout=20000)
                                    site_page.wait_for_load_state("networkidle", timeout=10000)
                                    site_html = site_page.content()
                                    site_page.close()

                                    emails = _emails_from_html(site_html)
                                    if not emails:
                                        for path in ["/contact", "/inquiry", "/toiawase"]:
                                            try:
                                                sp2 = context.new_page()
                                                sp2.goto(site_url.rstrip("/") + path, timeout=10000)
                                                sp2.wait_for_load_state("networkidle", timeout=8000)
                                                emails = _emails_from_html(sp2.content())
                                                sp2.close()
                                                if emails:
                                                    break
                                            except Exception:
                                                pass
                                            time.sleep(0.3)
                                    if emails:
                                        email = emails[0]
                                    time.sleep(0.5)
                                except Exception as e:
                                    print(f"  site error: {e}")

                            if not email or email in existing:
                                if email:
                                    print(f"  DUP: {email}")
                                continue

                            row = {
                                "company_name": name,
                                "email": email,
                                "url": site_url or detail_url,
                                "phone": phone,
                                "address": address,
                                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            }
                            writer.writerow(row)
                            f.flush()
                            existing.add(email)
                            found += 1
                            print(f"  [{found}] {name[:30]} | {email}")

                        # 次ページへ
                        next_btn = page.query_selector("a.next, a[rel='next'], .pagination .next a")
                        if next_btn:
                            next_btn.click()
                            page.wait_for_load_state("networkidle", timeout=15000)
                            time.sleep(1.5)
                            current_page += 1
                        else:
                            break

                except Exception as e:
                    print(f"  エラー ({pref_name}): {e}")
                    continue

                time.sleep(2.0)

        browser.close()

    print(f"\n完了: {found}件追加 → {LEADS_FILE}")


def _parse_results(html: str) -> list[dict]:
    """検索結果HTMLから事務所情報リストを抽出"""
    offices = []
    # Drupalのビュー結果行を抽出（構造はサイトによって異なるため複数パターン試す）
    rows = re.split(r'(?=<div[^>]+class="[^"]*views-row[^"]*")', html)
    for row in rows[1:]:  # 最初の分割は前置きHTML
        name_m = re.search(
            r'(?:field-content|field-name)[^>]*>\s*<(?:span|div|h[1-6]|a)[^>]*>([^<]{2,60})</(?:span|div|h[1-6]|a)>',
            row
        )
        phone_m = re.search(r'(\d{2,4}[-－]\d{2,4}[-－]\d{3,4})', row)
        link_m = re.search(r'href="(/search/[^"]+)"', row)
        addr_m = re.search(r'(?:〒|住所)[^\d]*?([\d\-〒]{0,10}\s*[東西南北都道府県]{1,4}[^<\n]{3,50})', row)

        if not name_m:
            continue
        name = name_m.group(1).strip()
        # 行政書士事務所っぽい名前のみ
        if not any(kw in name for kw in ["事務所", "行政書士", "法人", "オフィス"]):
            continue

        detail_url = ""
        if link_m:
            detail_url = "https://www.gyosei.or.jp" + link_m.group(1)

        offices.append({
            "name": name,
            "phone": phone_m.group(1) if phone_m else "",
            "address": addr_m.group(1).strip() if addr_m else "",
            "url": detail_url,
        })

    return offices


if __name__ == "__main__":
    main()
