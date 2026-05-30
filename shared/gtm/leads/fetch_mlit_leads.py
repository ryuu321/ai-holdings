"""
MLIT 建設業者データベースから汎用リード収集スクリプト
  python fetch_mlit_leads.py --output path/to/leads.csv --koumoku 09,17 [--limit 100] [--prefs 13,27]

工種コード (etsuran2.mlit.go.jp):
  01=建築  02=土木  03=大工  04=左官  05=とび  06=電気  07=管工事
  09=塗装  10=屋根  17=内装  18=防水  21=造園  27=解体

出力: CSV (company_name, email, url, phone, address, scraped_at)
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

HEADERS = {
    "User-Agent": "TextSeriesBot/1.0 (+mailto:ryuumg03@gmail.com)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ja,en-US;q=0.7",
}

DEFAULT_PREFS = [13, 27, 14, 23, 11, 12, 1, 28, 40, 26, 34, 4, 22]
DEFAULT_KYOKA_TYPES = ["1", "2"]

MLIT_BASE = "https://etsuran2.mlit.go.jp/KENSETSU"
MLIT_LIST = f"{MLIT_BASE}/kensetsuKensaku.do"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "sentry", "google",
              "schema.org", "w3.org", "mlit.go.jp", "test@", "info@example"]

_COMPANY_KW = ["株式会社", "有限会社", "合同会社", "一般社団法人"]


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
        if e.split(".")[-1].lower() in {"png", "jpg", "gif", "svg", "pdf", "zip"}:
            continue
        if e not in result:
            result.append(e)
    return result[:2]


def _get_companies(pref_code: int, koumoku: str, kyoka: str,
                   page: int = 1, count: int = 100) -> list[dict]:
    params = urllib.parse.urlencode({
        "kenCode": f"{pref_code:02d}",
        "koumokuCode": koumoku,
        "kyokaKubun": kyoka,
        "dispCount": str(count),
        "pageNo": str(page),
    }).encode("utf-8")
    req = urllib.request.Request(
        MLIT_LIST,
        data=params,
        headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            enc = r.headers.get_content_charset("utf-8")
            html = raw.decode(enc or "utf-8", errors="replace")
    except Exception as e:
        print(f"  fetch error {MLIT_LIST[:60]}: {e}")
        html = ""
    if not html:
        return []

    companies = []
    for row in re.split(r'(?=<tr[^>]*>)', html):
        if not any(kw in row for kw in _COMPANY_KW):
            continue
        name_match = re.search(
            r'<td[^>]*>([^<]{2,40}(?:株式会社|有限会社|合同会社)[^<]{0,40})</td>', row
        ) or re.search(
            r'<td[^>]*>((?:株式会社|有限会社|合同会社)[^<]{2,40})</td>', row
        )
        if not name_match:
            continue
        name = name_match.group(1).strip()
        link = re.search(r'href=["\']([^"\']+kensetsuDetail[^"\']+)["\']', row, re.IGNORECASE)
        detail_url = ""
        if link:
            href = link.group(1)
            detail_url = href if href.startswith("http") else MLIT_BASE + "/" + href.lstrip("/")
        phone_m = re.search(r'(\d{2,4}[-\-]\d{2,4}[-\-]\d{3,4})', row)
        companies.append({
            "company_name": name,
            "detail_url": detail_url,
            "phone": phone_m.group(1) if phone_m else "",
        })
    return companies


def _get_contact(detail_url: str) -> tuple[str, str, str]:
    if not detail_url:
        return "", "", ""
    html = _fetch(detail_url)
    if not html:
        return "", "", ""

    hp_match = re.search(
        r'(?:ホームページ|HP|URL|website)[^<]{0,50}<[^>]*>\s*<a[^>]+href="(https?://[^"]+)"',
        html, re.IGNORECASE
    ) or re.search(
        r'href="(https?://(?!(?:etsuran|mlit\.go\.jp|cloudflare|google))[^"]+)"', html
    )
    site_url = hp_match.group(1) if hp_match else ""
    addr_m = re.search(r'〒[\d\-]+\s*([^<\n]{5,60})', html)
    address = addr_m.group(0).strip() if addr_m else ""

    emails = _emails_from_html(html)
    if emails:
        return emails[0], site_url, address

    if site_url:
        site_html = _fetch(site_url)
        if site_html:
            emails = _emails_from_html(site_html)
            if not emails:
                for path in ["/contact", "/inquiry", "/toiawase", "/about"]:
                    h2 = _fetch(site_url.rstrip("/") + path)
                    emails = _emails_from_html(h2)
                    if emails:
                        break
                    time.sleep(0.3)
            if emails:
                return emails[0], site_url, address
        time.sleep(0.5)

    return "", site_url, address


def load_existing(leads_file: Path) -> set[str]:
    if not leads_file.exists():
        return set()
    with open(leads_file, encoding="utf-8", newline="") as f:
        return {row.get("email", "") for row in csv.DictReader(f) if row.get("email")}


def main():
    parser = argparse.ArgumentParser(description="MLIT建設業DBから汎用リード収集")
    parser.add_argument("--output", required=True, help="出力 leads.csv パス")
    parser.add_argument("--koumoku", required=True,
                        help="カンマ区切り工種コード (例: 09,17)")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--prefs", type=str, default="",
                        help="カンマ区切り都道府県コード (例: 13,27)")
    parser.add_argument("--pages", type=int, default=3)
    args = parser.parse_args()

    leads_file = Path(args.output)
    leads_file.parent.mkdir(parents=True, exist_ok=True)
    koumoku_codes = [c.strip() for c in args.koumoku.split(",") if c.strip()]
    prefs = [int(p) for p in args.prefs.split(",") if p.strip()] if args.prefs else DEFAULT_PREFS
    limit = args.limit if args.limit > 0 else 99999

    existing = load_existing(leads_file)
    print(f"既存リード: {len(existing)}件 | 工種: {koumoku_codes}")

    write_header = not leads_file.exists()
    found = 0

    with open(leads_file, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["company_name", "email", "url", "phone", "address", "scraped_at"]
        )
        if write_header:
            writer.writeheader()

        for pref_code in prefs:
            if found >= limit:
                break
            print(f"\n[都道府県 {pref_code:02d}]")
            for koumoku in koumoku_codes:
                if found >= limit:
                    break
                for kyoka in DEFAULT_KYOKA_TYPES:
                    if found >= limit:
                        break
                    for page in range(1, args.pages + 1):
                        if found >= limit:
                            break
                        companies = _get_companies(pref_code, koumoku, kyoka, page)
                        print(f"  [工種{koumoku}/許可{kyoka}/P{page}] {len(companies)}社")
                        if not companies:
                            break
                        for c in companies:
                            if found >= limit:
                                break
                            email, url, address = _get_contact(c.get("detail_url", ""))
                            if not email or email in existing:
                                if email:
                                    print(f"  DUP: {email}")
                                continue
                            row = {
                                "company_name": c["company_name"],
                                "email": email,
                                "url": url,
                                "phone": c.get("phone", ""),
                                "address": address,
                                "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                            }
                            writer.writerow(row)
                            f.flush()
                            existing.add(email)
                            found += 1
                            print(f"  [{found}] {c['company_name'][:30]} | {email}")
                            time.sleep(0.5)
                        time.sleep(1.5)

    print(f"\n完了: {found}件追加 → {leads_file}")


if __name__ == "__main__":
    main()
