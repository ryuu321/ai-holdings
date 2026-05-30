"""
MLIT 建設業者データベースから建設・工務店リードを収集
  python fetch_mlit_kensetsu_leads.py [--limit 100] [--prefs 13,27,14]

MLIT建設業データベース: https://etsuran2.mlit.go.jp/KENSETSU/
注意: DNS解決がローカル環境で失敗する場合はGitHub Actions上で実行してください。

出力: leads.csv (company_name, email, url, phone, address, scraped_at)
"""
import argparse
import csv
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_DIR = Path(__file__).parent
LEADS_FILE = _DIR / "leads.csv"

HEADERS = {
    "User-Agent": "KenTextBot/1.0 (+mailto:ryuumg03@gmail.com)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ja,en-US;q=0.7",
}

# 都道府県コード（人口多い順）
DEFAULT_PREFS = [13, 27, 14, 23, 11, 12, 1, 28, 40, 26, 34, 4, 22]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "sentry", "google",
              "schema.org", "w3.org", "mlit.go.jp", "test@", "info@example"]

# MLIT 建設業者データベース
# etsuran2.mlit.go.jp はetsuran.mlit.go.jpの新版
MLIT_KENSETSU_BASE = "https://etsuran2.mlit.go.jp/KENSETSU"
MLIT_KENSETSU_LIST = f"{MLIT_KENSETSU_BASE}/kensetsuKensaku.do"

# 工種コード（建築工事業=01, 土木工事業=02, 大工工事業=03, 左官工事業=04, など）
# 建築全般 = 01 / 管工事=07 / 電気工事=06 / 内装=17 / 塗装=09 / リフォーム目的では01+17
KOUMOKU_CODES = ["01", "17", "09"]  # 建築・内装・塗装

# 許可種別: 1=知事許可, 2=大臣許可
KYOKA_TYPES = ["1", "2"]

_COMPANY_KEYWORDS = ["株式会社", "有限会社", "合同会社", "一般社団法人"]


def _fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            enc = r.headers.get_content_charset("utf-8")
            return raw.decode(enc or "utf-8", errors="replace")
    except Exception as e:
        print(f"  fetch error {url[:60]}: {e}")
        return ""


def _emails_from_html(html: str) -> list[str]:
    found = EMAIL_RE.findall(html)
    result = []
    for e in found:
        e = e.lower().rstrip(".")
        if any(s in e for s in EMAIL_SKIP):
            continue
        tld = e.split(".")[-1].lower()
        if tld in {"png", "jpg", "gif", "svg", "pdf", "zip"}:
            continue
        if e not in result:
            result.append(e)
    return result[:2]


def _get_companies_from_mlit(pref_code: int, koumoku: str, kyoka: str,
                               page: int = 1, count: int = 100) -> list[dict]:
    """MLIT建設業者データベースから会社リストを取得"""
    params = urllib.parse.urlencode({
        "kenCode": f"{pref_code:02d}",
        "koumokuCode": koumoku,
        "kyokaKubun": kyoka,
        "dispCount": str(count),
        "pageNo": str(page),
    })
    url = f"{MLIT_KENSETSU_LIST}?{params}"
    html = _fetch(url)
    if not html:
        return []

    companies = []
    # 会社名・詳細リンクを抽出
    # テーブルの各行から会社名と詳細URLを取得
    rows = re.split(r'(?=<tr[^>]*>)', html)
    for row in rows:
        # 法人名を含む行のみ処理
        if not any(kw in row for kw in _COMPANY_KEYWORDS):
            continue
        # 法人名を抽出
        name_match = re.search(
            r'<td[^>]*>([^<]{2,40}(?:株式会社|有限会社|合同会社)[^<]{0,40})</td>',
            row
        )
        if not name_match:
            # 別パターン（株式会社が前置き）
            name_match = re.search(
                r'<td[^>]*>((?:株式会社|有限会社|合同会社)[^<]{2,40})</td>',
                row
            )
        if not name_match:
            continue
        company_name = name_match.group(1).strip()

        # 詳細リンク
        link_match = re.search(r'href=["\']([^"\']+kensetsuDetail[^"\']+)["\']', row, re.IGNORECASE)
        detail_url = ""
        if link_match:
            href = link_match.group(1)
            if href.startswith("http"):
                detail_url = href
            else:
                detail_url = MLIT_KENSETSU_BASE + "/" + href.lstrip("/")

        # 電話番号
        phone_match = re.search(r'(\d{2,4}[-\-]\d{2,4}[-\-]\d{3,4})', row)
        phone = phone_match.group(1) if phone_match else ""

        companies.append({
            "company_name": company_name,
            "detail_url": detail_url,
            "phone": phone,
        })

    return companies


def _get_company_website(company_name: str, detail_url: str) -> tuple[str, str, str]:
    """
    会社詳細ページからウェブサイトURLとメールを取得。
    戻り値: (email, url, address)
    """
    if detail_url:
        html = _fetch(detail_url)
        if html:
            # ホームページURL
            hp_match = re.search(
                r'(?:ホームページ|HP|URL|website)[^<]{0,50}<[^>]*>\s*<a[^>]+href="(https?://[^"]+)"',
                html, re.IGNORECASE
            )
            if not hp_match:
                hp_match = re.search(
                    r'href="(https?://(?!(?:etsuran|mlit\.go\.jp|cloudflare|google))[^"]+)"',
                    html
                )

            website_url = hp_match.group(1) if hp_match else ""

            # 住所
            addr_match = re.search(r'〒[\d\-]+\s*([^<\n]{5,60})', html)
            address = addr_match.group(0).strip() if addr_match else ""

            # 詳細ページ自体にメールがある場合
            emails = _emails_from_html(html)
            if emails:
                return emails[0], website_url, address

            # ウェブサイトに行ってメールを取得
            if website_url:
                site_html = _fetch(website_url)
                if site_html:
                    emails = _emails_from_html(site_html)
                    if not emails:
                        base = website_url.rstrip("/")
                        for path in ["/contact", "/inquiry", "/toiawase", "/about"]:
                            h2 = _fetch(base + path)
                            emails = _emails_from_html(h2)
                            if emails:
                                break
                            time.sleep(0.3)
                    if emails:
                        return emails[0], website_url, address
                time.sleep(0.5)

            return "", website_url, address

    return "", "", ""


def load_existing() -> set[str]:
    if not LEADS_FILE.exists():
        return set()
    with open(LEADS_FILE, encoding="utf-8", newline="") as f:
        return {row.get("email", "") for row in csv.DictReader(f) if row.get("email")}


def main():
    parser = argparse.ArgumentParser(description="MLIT建設業者データベースからリード収集")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--prefs", type=str, default="",
                        help="カンマ区切りの都道府県コード (例: 13,27)")
    parser.add_argument("--pages", type=int, default=3, help="各条件で取得するページ数")
    args = parser.parse_args()

    prefs = [int(p) for p in args.prefs.split(",") if p.strip()] if args.prefs else DEFAULT_PREFS
    limit = args.limit if args.limit > 0 else 99999

    existing = load_existing()
    print(f"既存リード: {len(existing)}件")

    write_header = not LEADS_FILE.exists()
    found = 0

    with open(LEADS_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["company_name", "email", "url", "phone", "address", "scraped_at"]
        )
        if write_header:
            writer.writeheader()

        for pref_code in prefs:
            if found >= limit:
                break

            print(f"\n[都道府県 {pref_code:02d}] ...")

            for koumoku in KOUMOKU_CODES:
                if found >= limit:
                    break

                for kyoka in KYOKA_TYPES:
                    if found >= limit:
                        break

                    for page in range(1, args.pages + 1):
                        if found >= limit:
                            break

                        print(f"  [工種{koumoku}/許可{kyoka}/Page{page}] ...")
                        companies = _get_companies_from_mlit(pref_code, koumoku, kyoka, page)
                        print(f"    {len(companies)}社検出")

                        if not companies:
                            break

                        for company in companies:
                            if found >= limit:
                                break

                            name = company["company_name"]
                            email, url, address = _get_company_website(
                                name, company.get("detail_url", "")
                            )

                            if not email:
                                continue
                            if email in existing:
                                print(f"  DUP: {email}")
                                continue

                            row = {
                                "company_name": name,
                                "email": email,
                                "url": url,
                                "phone": company.get("phone", ""),
                                "address": address,
                                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            }
                            writer.writerow(row)
                            f.flush()
                            existing.add(email)
                            found += 1
                            print(f"  [{found}] {name[:30]} | {email}")
                            time.sleep(0.5)

                        time.sleep(1.5)

    print(f"\n完了: {found}件追加 → {LEADS_FILE}")


if __name__ == "__main__":
    main()
