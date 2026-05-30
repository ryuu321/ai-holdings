"""
freee認定アドバイザーディレクトリから税理士リードを収集
  python fetch_freee_leads.py [--limit 100] [--prefs 13,27,14,23]

URL: https://search-advisors.freee.co.jp/advisors/search/01_{pref_en}?page=N
各プロフィールのホームページURLを取得 → そのサイトからメールを抽出

出力: leads.csv (company_name, email, url, phone, address, scraped_at)
"""
import argparse
import csv
import re
import sys
import time
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

BASE = "https://search-advisors.freee.co.jp"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ja,en-US;q=0.7",
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "freee.co.jp", "google",
              "schema.org", "w3.org", "placeholder", "test@", "sentry",
              "cloudflare", "amazonaws", "sendgrid"]

# 都道府県コード → freee URL で使う英語名
PREF_EN = {
    1: "hokkaido", 4: "miyagi", 8: "ibaraki", 9: "tochigi",
    10: "gunma", 11: "saitama", 12: "chiba", 13: "tokyo",
    14: "kanagawa", 15: "niigata", 17: "ishikawa", 20: "nagano",
    22: "shizuoka", 23: "aichi", 24: "mie", 25: "shiga",
    26: "kyoto", 27: "osaka", 28: "hyogo", 29: "nara",
    33: "okayama", 34: "hiroshima", 37: "kagawa", 40: "fukuoka",
    43: "kumamoto", 47: "okinawa",
}
DEFAULT_PREFS = [13, 27, 14, 23, 11, 12, 1, 28, 40, 26, 34, 4, 22]


def _fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            enc = r.headers.get_content_charset("utf-8")
            return raw.decode(enc or "utf-8", errors="replace")
    except Exception as e:
        print(f"  fetch error {url[:70]}: {e}")
        return ""


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


def _get_advisor_ids(pref_en: str, page: int) -> list[str]:
    """一覧ページからアドバイザーIDのリストを返す"""
    url = f"{BASE}/advisors/search/01_{pref_en}?page={page}"
    html = _fetch(url)
    if not html:
        return []
    # /advisors/{数字} の形式のリンクを抽出（重複除去・一覧ページ内のリンク）
    ids = re.findall(r'href="/advisors/(\d+)"', html)
    # 重複排除しつつ順序保持
    seen: set[str] = set()
    result = []
    for aid in ids:
        if aid not in seen:
            seen.add(aid)
            result.append(aid)
    return result


def _get_profile(advisor_id: str) -> dict:
    """プロフィールページから事務所名・電話・ホームページURLを取得"""
    url = f"{BASE}/advisors/{advisor_id}"
    html = _fetch(url)
    if not html:
        return {}

    # ホームページURL: <a href="https://...">...</a> でfreee以外の外部リンク
    site_m = re.search(
        r'href="(https?://(?!(?:search-advisors|advisor|freee)[^"]*)[^"]{5,})"',
        html
    )
    site_url = site_m.group(1).strip() if site_m else ""

    # 事務所名
    name_m = re.search(
        r'<h1[^>]*>([^<]{3,80})</h1>|<title[^>]*>([^|｜–\-<]{3,60})',
        html
    )
    name = ""
    if name_m:
        name = (name_m.group(1) or name_m.group(2) or "").strip()

    # 電話番号
    phone_m = re.search(r'(\d{2,4}-\d{2,4}-\d{4})', html)
    phone = phone_m.group(1) if phone_m else ""

    # 住所
    addr_m = re.search(r'〒\d{3}-\d{4}\s*([^\n<]{5,60})', html)
    address = addr_m.group(0).strip() if addr_m else ""

    return {"name": name, "site_url": site_url, "phone": phone, "address": address}


def _email_from_site(site_url: str) -> str:
    """オフィスサイトからメールアドレスを取得"""
    if not site_url:
        return ""
    html = _fetch(site_url)
    if html:
        emails = _emails_from_html(html)
        if emails:
            return emails[0]
        for path in ["/contact", "/inquiry", "/toiawase", "/about"]:
            h2 = _fetch(site_url.rstrip("/") + path)
            emails = _emails_from_html(h2)
            if emails:
                return emails[0]
            time.sleep(0.3)
    return ""


def load_existing() -> set[str]:
    if not LEADS_FILE.exists():
        return set()
    with open(LEADS_FILE, encoding="utf-8", newline="") as f:
        return {row.get("email", "") for row in csv.DictReader(f) if row.get("email")}


def main():
    parser = argparse.ArgumentParser(description="freee認定アドバイザーから税理士リード収集")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--prefs", type=str, default="")
    parser.add_argument("--pages", type=int, default=5)
    args = parser.parse_args()

    pref_codes = [int(p) for p in args.prefs.split(",") if p.strip()] if args.prefs else DEFAULT_PREFS
    limit = args.limit if args.limit > 0 else 99999

    existing = load_existing()
    print(f"既存リード: {len(existing)}件")

    write_header = not LEADS_FILE.exists()
    found = 0

    with open(LEADS_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["company_name", "email", "url", "phone", "address", "scraped_at"]
        )
        if write_header:
            writer.writeheader()

        for pref_code in pref_codes:
            if found >= limit:
                break
            pref_en = PREF_EN.get(pref_code)
            if not pref_en:
                print(f"  スキップ: 都道府県コード {pref_code} は未マップ")
                continue
            print(f"\n[都道府県 {pref_code:02d} / {pref_en}]")

            for page in range(1, args.pages + 1):
                if found >= limit:
                    break

                advisor_ids = _get_advisor_ids(pref_en, page)
                print(f"  [Page {page}] {len(advisor_ids)}件のID取得")
                if not advisor_ids:
                    break

                new_on_page = 0
                for aid in advisor_ids:
                    if found >= limit:
                        break

                    profile = _get_profile(aid)
                    if not profile:
                        continue

                    site_url = profile.get("site_url", "")
                    name = profile.get("name", "")
                    email = _email_from_site(site_url)

                    if not email or email in existing:
                        if email:
                            print(f"  DUP: {email}")
                        time.sleep(0.5)
                        continue

                    row = {
                        "company_name": name,
                        "email": email,
                        "url": site_url,
                        "phone": profile.get("phone", ""),
                        "address": profile.get("address", ""),
                        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    writer.writerow(row)
                    f.flush()
                    existing.add(email)
                    found += 1
                    new_on_page += 1
                    print(f"  [{found}] {name[:35]} | {email}")
                    time.sleep(1.0)

                if new_on_page == 0:
                    print(f"  新規なし → 次の都道府県へ")
                    break
                time.sleep(2.0)

    print(f"\n完了: {found}件追加 → {LEADS_FILE}")


if __name__ == "__main__":
    main()
