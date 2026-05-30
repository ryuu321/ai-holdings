"""
MHLW 医療機能情報公表システム (mfis.mhlw.go.jp) からクリニックリードを収集
  python fetch_mhlw_iintext_leads.py [--limit 100] [--prefs 13,27,14,23]

対象: 内科・外科・クリニック・診療所（診療科目コードで絞り込み）
注意: DNS解決がローカル環境で失敗する場合はGitHub Actions上で実行してください。

出力: leads.csv (company_name, email, url, phone, address, scraped_at)
"""
import argparse
import csv
import json
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
    "User-Agent": "IinTextBot/1.0 (+mailto:ryuumg03@gmail.com)",
    "Accept": "application/json, text/html",
    "Accept-Language": "ja,en-US;q=0.7",
}

DEFAULT_PREFS = [13, 27, 14, 23, 11, 12, 1, 28, 40, 26, 34, 4, 22]

# MHLW 医療機能情報公表システム API
MFIS_BASE = "https://mfis.mhlw.go.jp"

# 施設種別: 1=病院, 2=一般診療所（クリニック）
FACILITY_TYPES = ["2"]  # クリニック・診療所に絞る
# 診療科目コード（主要なもの）
DIAGNOSTIC_CODES = ["01", "02", "15"]  # 01=内科, 02=外科, 15=整形外科

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "google", "mhlw.go.jp",
              "schema.org", "w3.org", "placeholder", "test@"]


def _fetch_json(url: str) -> dict | list | None:
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
        if e.split(".")[-1].lower() in {"png", "jpg", "gif", "svg", "pdf", "js"}:
            continue
        if e not in result:
            result.append(e)
    return result[:2]


def _get_facilities(pref_cd: str, facility_type: str,
                    diag_code: str, page: int = 1) -> list[dict]:
    """医療機能情報公表システムから診療所リスト取得"""
    # パターン1: mfis.mhlw.go.jp REST API
    params = urllib.parse.urlencode({
        "prefCd": pref_cd,
        "facilityTypeCd": facility_type,
        "diagnosticDeptCd": diag_code,
        "pageNo": page,
        "dispCount": 50,
    })
    url = f"{MFIS_BASE}/api/facility/search?{params}"
    data = _fetch_json(url)
    if data:
        if isinstance(data, list):
            return data
        for key in ["list", "facilityList", "items", "result", "data"]:
            if key in data and isinstance(data[key], list):
                return data[key]

    # パターン2: 都道府県別APIエンドポイント（旧システム互換）
    url2 = (f"{MFIS_BASE}/{pref_cd}/api/facilities"
            f"?type={facility_type}&dept={diag_code}&page={page}")
    data2 = _fetch_json(url2)
    if data2:
        if isinstance(data2, list):
            return data2
        for key in ["list", "facilityList", "items", "result"]:
            if key in data2 and isinstance(data2[key], list):
                return data2[key]

    return []


def _extract_info(item: dict) -> dict:
    result = {"company_name": "", "url": "", "phone": "", "address": ""}
    for key in ["facilityName", "name", "iryokikanName", "kikanName"]:
        if item.get(key):
            result["company_name"] = str(item[key]).strip()
            break
    for key in ["homepageUrl", "url", "website", "hp"]:
        val = item.get(key, "")
        if val and str(val).startswith("http"):
            result["url"] = str(val).strip()
            break
    for key in ["tel", "phone", "telNo", "telNumber"]:
        if item.get(key):
            result["phone"] = str(item[key]).strip()
            break
    for key in ["address", "addr", "jusho", "shozaiAddress"]:
        if item.get(key):
            result["address"] = str(item[key]).strip()
            break
    return result


def load_existing() -> set[str]:
    if not LEADS_FILE.exists():
        return set()
    with open(LEADS_FILE, encoding="utf-8", newline="") as f:
        return {row.get("email", "") for row in csv.DictReader(f) if row.get("email")}


def main():
    parser = argparse.ArgumentParser(description="MHLW医療機能情報からクリニックリード収集")
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
            pref_str = f"{pref_code:02d}"
            print(f"\n[都道府県 {pref_str}]")

            for ftype in FACILITY_TYPES:
                for diag in DIAGNOSTIC_CODES:
                    for page in range(1, args.pages + 1):
                        if found >= limit:
                            break

                        facilities = _get_facilities(pref_str, ftype, diag, page)
                        print(f"  [施設{ftype}/診療科{diag}/P{page}] {len(facilities)}件")
                        if not facilities:
                            break

                        for item in facilities:
                            if found >= limit:
                                break

                            info = _extract_info(item)
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

    print(f"\n完了: {found}件追加 → {LEADS_FILE}")


if __name__ == "__main__":
    main()
