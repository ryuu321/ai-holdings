"""
MHLW 介護サービス情報公表システムから汎用リード収集スクリプト
  python fetch_mhlw_leads.py --output path/to/leads.csv --service-codes 310,320 [--limit 100]

主要サービス種別コード (kaigokensaku.mhlw.go.jp):
  110=訪問介護  111=訪問入浴  113=訪問看護  120=訪問リハ
  130=通所介護  141=通所リハ  150=短期入所生活  160=短期入所療養
  210=グループホーム  260=特定施設  310=老健  320=特養
  400=居宅介護支援  421=予防支援

出力: CSV (company_name, email, url, phone, address, scraped_at)
"""
import argparse
import csv
import json
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

HEADERS = {
    "User-Agent": "TextSeriesBot/1.0 (+mailto:ryuumg03@gmail.com)",
    "Accept": "application/json, text/html",
    "Accept-Language": "ja,en-US;q=0.7",
}

DEFAULT_PREFS = [13, 27, 14, 23, 11, 12, 1, 28, 40, 26, 34, 4, 22]
BASE_API = "https://api.kaigokensaku.mhlw.go.jp"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "sentry", "google",
              "schema.org", "w3.org", "placeholder", "test@", "mhlw.go.jp"]


def _fetch_json(url: str) -> dict | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"  API error {url[:80]}: {e}")
        return None


def _fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")
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
        if e.split("@")[-1].lower() in {"png", "jpg", "gif", "svg", "pdf"}:
            continue
        if e not in result:
            result.append(e)
    return result[:2]


def _get_providers(pref_cd: str, service_code: str, page: int = 1) -> list[dict]:
    url = (f"{BASE_API}/{pref_cd}/api/index.php"
           f"?kind=1&serviceTypeCode={service_code}&page={page}&detail=0")
    data = _fetch_json(url)
    if not data:
        url2 = (f"{BASE_API}/{pref_cd}/api/serviceType/{service_code}/list.json"
                f"?page={page}")
        data = _fetch_json(url2)
    if not data:
        return []
    if isinstance(data, list):
        return data
    for key in ["list", "jigyosho", "items", "result", "data"]:
        if key in data and isinstance(data[key], list):
            return data[key]
    return []


def _extract(item: dict) -> dict:
    result = {"company_name": "", "url": "", "phone": "", "address": "", "jigyosho_no": ""}
    for key in ["jigyoshoName", "name", "officeName", "service_name"]:
        if item.get(key):
            result["company_name"] = str(item[key]).strip()
            break
    for key in ["jigyoshoNo", "no", "officeNo", "jigyosho_no"]:
        if item.get(key):
            result["jigyosho_no"] = str(item[key]).strip()
            break
    for key in ["homepageUrl", "url", "website", "hp"]:
        val = item.get(key, "")
        if val and str(val).startswith("http"):
            result["url"] = str(val).strip()
            break
    for key in ["tel", "phone", "telNo"]:
        if item.get(key):
            result["phone"] = str(item[key]).strip()
            break
    for key in ["address", "addr", "jusho"]:
        if item.get(key):
            result["address"] = str(item[key]).strip()
            break
    return result


def _get_detail(pref_cd: str, jigyosho_no: str, service_code: str) -> dict:
    url = (f"{BASE_API}/{pref_cd}/api/index.php"
           f"?kind=2&jigyoshoNo={jigyosho_no}&serviceTypeCode={service_code}")
    data = _fetch_json(url)
    return data if isinstance(data, dict) else {}


def load_existing(leads_file: Path) -> set[str]:
    if not leads_file.exists():
        return set()
    with open(leads_file, encoding="utf-8", newline="") as f:
        return {row.get("email", "") for row in csv.DictReader(f) if row.get("email")}


def main():
    parser = argparse.ArgumentParser(description="MHLW介護サービス情報から汎用リード収集")
    parser.add_argument("--output", required=True, help="出力 leads.csv パス")
    parser.add_argument("--service-codes", required=True,
                        help="カンマ区切りサービス種別コード (例: 110,113)")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--prefs", type=str, default="")
    parser.add_argument("--pages", type=int, default=5)
    args = parser.parse_args()

    leads_file = Path(args.output)
    leads_file.parent.mkdir(parents=True, exist_ok=True)
    service_codes = [c.strip() for c in args.service_codes.split(",") if c.strip()]
    prefs = [int(p) for p in args.prefs.split(",") if p.strip()] if args.prefs else DEFAULT_PREFS
    limit = args.limit if args.limit > 0 else 99999

    existing = load_existing(leads_file)
    print(f"既存リード: {len(existing)}件 | サービスコード: {service_codes}")

    write_header = not leads_file.exists()
    found = 0

    with open(leads_file, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["company_name", "email", "url", "phone", "address", "scraped_at"]
        )
        if write_header:
            writer.writeheader()

        for pref_cd in prefs:
            if found >= limit:
                break
            pref_str = f"{pref_cd:02d}"
            print(f"\n[都道府県 {pref_str}]")

            for sc in service_codes:
                for page in range(1, args.pages + 1):
                    if found >= limit:
                        break
                    providers = _get_providers(pref_str, sc, page)
                    print(f"  [コード{sc}/P{page}] {len(providers)}件")
                    if not providers:
                        break

                    for item in providers:
                        if found >= limit:
                            break
                        info = _extract(item)
                        company = info["company_name"]
                        if not company:
                            continue

                        url = info["url"]
                        email = ""

                        if url:
                            html = _fetch_html(url)
                            if html:
                                emails = _emails_from_html(html)
                                if not emails:
                                    for path in ["/contact", "/inquiry", "/toiawase"]:
                                        h2 = _fetch_html(url.rstrip("/") + path)
                                        emails = _emails_from_html(h2)
                                        if emails:
                                            break
                                        time.sleep(0.3)
                                if emails:
                                    email = emails[0]
                            time.sleep(0.5)

                        if not email and info.get("jigyosho_no"):
                            detail = _get_detail(pref_str, info["jigyosho_no"], sc)
                            if detail:
                                d2 = _extract(detail)
                                if d2["url"] and not url:
                                    url = d2["url"]
                                    html = _fetch_html(url)
                                    emails = _emails_from_html(html)
                                    if emails:
                                        email = emails[0]
                                    time.sleep(0.5)

                        if not email or email in existing:
                            if email:
                                print(f"  DUP: {email}")
                            continue

                        row = {
                            "company_name": company,
                            "email": email,
                            "url": url,
                            "phone": info["phone"],
                            "address": info["address"],
                            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                        }
                        writer.writerow(row)
                        f.flush()
                        existing.add(email)
                        found += 1
                        print(f"  [{found}] {company[:30]} | {email}")
                        time.sleep(0.3)

                    time.sleep(1.0)

    print(f"\n完了: {found}件追加 → {leads_file}")


if __name__ == "__main__":
    main()
