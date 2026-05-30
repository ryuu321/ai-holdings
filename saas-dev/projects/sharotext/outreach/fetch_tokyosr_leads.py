"""
東京都社会保険労務士会 会員検索からリードを収集
https://www.tokyosr.jp/member-search/

出力: leads.csv (company_name, email, url, phone, address, scraped_at)
"""
import argparse
import csv
import re
import sys
import time
import urllib.request
import urllib.parse
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
    "User-Agent": "SharoTextBot/1.0 (+mailto:ryuumg03@gmail.com)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ja,en-US;q=0.7",
}

BASE_URL = "https://www.tokyosr.jp"
LIST_URL = f"{BASE_URL}/member-search/search-result/?mode=2&p={{page}}&is_paging=1"
DETAIL_URL = f"{BASE_URL}/member-view/?member_id={{member_id}}&mode=2"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["tokyosr", "example", "w3.org", "schema", "google", "twitter", "noreply", "no-reply"]

# company name validations
_COMPANY_KW = ["社会保険労務士", "社労士", "SR事務所", "労務"]


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  fetch error {url[:60]}: {e}")
        return ""


def _extract_list_items(html: str) -> list[dict]:
    """リスト画面から member_id, 事務所名, 電話番号を抽出"""
    items = []
    # Each member is in a p-box-a div
    blocks = re.split(r'(?=<div class="p-box-a">)', html)
    for block in blocks:
        if 'p-box-a' not in block:
            continue
        # member_id from detail link
        mid_match = re.search(r'member_id=(\d+)', block)
        if not mid_match:
            continue
        member_id = mid_match.group(1)
        # office name
        belongs = re.search(r'class="belongs">([^<]+)<', block)
        # phone
        phone = re.search(r'(?:070|080|090|03|06|0[2-9]\d)-[\d\-（）]+', block)
        items.append({
            "member_id": member_id,
            "company_name": belongs.group(1).strip() if belongs else "",
            "phone": phone.group(0) if phone else "",
        })
    return items


def _extract_detail(html: str) -> dict:
    """詳細ページからメール・ウェブサイトを抽出"""
    # Email - it appears as "Email info@..."
    emails = EMAIL_RE.findall(html)
    email = next((e for e in emails if not any(s in e for s in EMAIL_SKIP)), "")

    # Website URL
    website = ""
    hp_match = re.search(r'ホームページ\s*</th>\s*<td[^>]*>\s*<a[^>]+href="(https?://[^"]+)"', html, re.IGNORECASE)
    if not hp_match:
        hp_match = re.search(r'href="(https?://(?!(?:www\.tokyosr|google|cloudflare|cdnjs|unpkg|twitter|youtube|privacymark|sr-shindan|tokyo-sr|shakaihokenroumushi|src-tokyo|koukensr))[^"]+)"', html)
    if hp_match:
        website = hp_match.group(1)

    # Address
    addr_match = re.search(r'〒[\d\-]+\s*([^<\n]{5,60})', html)
    address = addr_match.group(0).strip() if addr_match else ""

    return {"email": email, "url": website, "address": address}


def load_existing() -> set[str]:
    if not LEADS_FILE.exists():
        return set()
    with open(LEADS_FILE, encoding="utf-8", newline="") as f:
        return {row["email"] for row in csv.DictReader(f) if row.get("email")}


def main():
    parser = argparse.ArgumentParser(description="東京社労士会リード収集")
    parser.add_argument("--limit", type=int, default=50, help="取得上限（0=無制限）")
    parser.add_argument("--pages", type=int, default=10, help="スキャンするページ数")
    parser.add_argument("--skip-no-email", action="store_true", help="メールなしはスキップ")
    args = parser.parse_args()

    existing = load_existing()
    print(f"既存リード: {len(existing)}件")

    write_header = not LEADS_FILE.exists()
    found = 0
    limit = args.limit if args.limit > 0 else 99999

    with open(LEADS_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "email", "url", "phone", "address", "scraped_at"])
        if write_header:
            writer.writeheader()

        for page in range(1, args.pages + 1):
            if found >= limit:
                break

            print(f"\n[Page {page}] スキャン中...")
            html = _fetch(LIST_URL.format(page=page))
            if not html:
                break

            items = _extract_list_items(html)
            print(f"  {len(items)}件検出")

            for item in items:
                if found >= limit:
                    break

                company = item["company_name"]
                if not company:
                    continue

                # 詳細ページ取得
                detail_html = _fetch(DETAIL_URL.format(member_id=item["member_id"]))
                time.sleep(0.5)
                if not detail_html:
                    continue

                detail = _extract_detail(detail_html)
                email = detail["email"]

                if not email and args.skip_no_email:
                    print(f"  SKIP (no email): {company[:30]}")
                    continue

                if email and email in existing:
                    print(f"  DUP: {email}")
                    continue

                row = {
                    "company_name": company,
                    "email": email,
                    "url": detail["url"],
                    "phone": item["phone"],
                    "address": detail["address"],
                    "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                writer.writerow(row)
                f.flush()
                existing.add(email)
                found += 1
                print(f"  [{found}] {company[:30]} | {email or '(email未取得)'}")
                time.sleep(0.3)

            time.sleep(1.0)

    print(f"\n完了: {found}件追加 → {LEADS_FILE}")


if __name__ == "__main__":
    main()
