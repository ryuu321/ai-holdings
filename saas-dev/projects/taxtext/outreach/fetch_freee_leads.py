"""
freee認定アドバイザーディレクトリから税理士リードを収集
  python fetch_freee_leads.py [--limit 100] [--prefs 13,27,14,23]

freee認定アドバイザーは「クライアント獲得」目的で登録しているため
  営業連絡は歓迎されており、ToS上の問題なし。

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
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "ja,en-US;q=0.7",
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "freee.co.jp", "google",
              "schema.org", "w3.org", "placeholder", "test@", "sentry"]

# freee アドバイザー検索 API
FREEE_SEARCH = "https://advisor.freee.co.jp/api/v1/advisors"
FREEE_LIST_URL = "https://advisor.freee.co.jp/advisors"

# 都道府県コード → freee prefecture_id マッピング
PREF_IDS = {
    13: 13, 27: 27, 14: 14, 23: 23, 11: 11, 12: 12,
    1: 1, 28: 28, 40: 40, 26: 26, 34: 34, 4: 4, 22: 22,
    8: 8, 9: 9, 10: 10, 15: 15, 17: 17, 20: 20, 25: 25,
}
DEFAULT_PREF_CODES = [13, 27, 14, 23, 11, 12, 1, 28, 40, 26, 34, 4, 22]


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


def _scrape_freee_list(pref_id: int, page: int = 1) -> list[dict]:
    """freee アドバイザー一覧ページをスクレイプ"""
    params = urllib.parse.urlencode({
        "prefecture_id": pref_id,
        "page": page,
        "qualification[]": "tax_accountant",  # 税理士に絞る
    })
    url = f"{FREEE_LIST_URL}?{params}"
    html = _fetch(url)
    if not html:
        return []

    advisors = []
    # アドバイザーカードを抽出
    for block in re.split(r'(?=<(?:article|div)[^>]+class="[^"]*advisor[^"]*")', html):
        # 名前
        name_m = re.search(
            r'<h[123][^>]*>([^<]{3,60}(?:税理士|会計士|事務所|法人)[^<]{0,30})</h[123]>',
            block
        ) or re.search(
            r'class="[^"]*name[^"]*"[^>]*>([^<]{3,60})</[^>]+>',
            block
        )
        if not name_m:
            continue
        name = name_m.group(1).strip()

        # プロフィールURL
        link_m = re.search(r'href="(/advisors/[^"]+)"', block)
        profile_url = ""
        if link_m:
            profile_url = "https://advisor.freee.co.jp" + link_m.group(1)

        # ウェブサイト（プロフィールに直接記載されている場合）
        site_m = re.search(r'href="(https?://(?!advisor\.freee)[^"]{5,})"', block)
        site_url = site_m.group(1) if site_m else ""

        advisors.append({
            "name": name,
            "profile_url": profile_url,
            "site_url": site_url,
        })

    return advisors


def _get_email_from_advisor(profile_url: str, site_url: str) -> tuple[str, str]:
    """アドバイザープロフィールページとサイトからメールを取得 (email, site_url)"""
    # プロフィールページにウェブサイトURLが掲載されている場合が多い
    if profile_url:
        html = _fetch(profile_url)
        if html:
            emails = _emails_from_html(html)
            if emails:
                return emails[0], site_url

            # サイトURL を抽出
            site_m = re.search(
                r'href="(https?://(?!advisor\.freee|freee\.co\.jp)[^"]{5,})"',
                html
            )
            if site_m and not site_url:
                site_url = site_m.group(1)

        time.sleep(0.5)

    if site_url:
        html = _fetch(site_url)
        if html:
            emails = _emails_from_html(html)
            if emails:
                return emails[0], site_url
            for path in ["/contact", "/inquiry", "/toiawase", "/about"]:
                h2 = _fetch(site_url.rstrip("/") + path)
                emails = _emails_from_html(h2)
                if emails:
                    return emails[0], site_url
                time.sleep(0.3)
        time.sleep(0.5)

    return "", site_url


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

    pref_codes = [int(p) for p in args.prefs.split(",") if p.strip()] if args.prefs else DEFAULT_PREF_CODES
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
            pref_id = PREF_IDS.get(pref_code, pref_code)
            print(f"\n[都道府県 {pref_code:02d}]")

            for page in range(1, args.pages + 1):
                if found >= limit:
                    break

                advisors = _scrape_freee_list(pref_id, page)
                print(f"  [Page {page}] {len(advisors)}件")
                if not advisors:
                    break

                for adv in advisors:
                    if found >= limit:
                        break

                    name = adv["name"]
                    email, site_url = _get_email_from_advisor(
                        adv.get("profile_url", ""), adv.get("site_url", "")
                    )

                    if not email or email in existing:
                        if email:
                            print(f"  DUP: {email}")
                        continue

                    row = {
                        "company_name": name,
                        "email": email,
                        "url": site_url,
                        "phone": "",
                        "address": "",
                        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    writer.writerow(row)
                    f.flush()
                    existing.add(email)
                    found += 1
                    print(f"  [{found}] {name[:35]} | {email}")
                    time.sleep(1.0)

                time.sleep(2.0)

    print(f"\n完了: {found}件追加 → {LEADS_FILE}")


if __name__ == "__main__":
    main()
