"""
介護サービス情報公表システム（MHLW）から訪問介護事業所リードを収集
  python fetch_mhlw_leads.py [--limit 100] [--prefs 13,14,27]

APIドキュメント: https://api.kaigokensaku.mhlw.go.jp/
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
    "User-Agent": "CareTextBot/1.0 (+mailto:ryuumg03@gmail.com)",
    "Accept": "application/json, text/html",
    "Accept-Language": "ja,en-US;q=0.7",
}

# 都道府県コード（人口多い順）
DEFAULT_PREFS = [13, 27, 14, 23, 11, 12, 1, 28, 40, 26, 34, 4, 22]

# 介護サービス種別コード
# 110 = 訪問介護、111 = 訪問入浴介護、113 = 訪問看護
SERVICE_CODES = ["110"]

BASE_API = "https://api.kaigokensaku.mhlw.go.jp"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "sentry", "google",
              "schema.org", "w3.org", "placeholder", "test@", "mhlw.go.jp"]


def _fetch_json(url: str, timeout: int = 20) -> dict | None:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        print(f"  API error {url[:80]}: {e}")
        return None


def _fetch_html(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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


def _get_providers_list(pref_cd: str, service_code: str, page: int = 1) -> list[dict]:
    """
    MHLW 介護サービス情報公表API から事業所一覧を取得。
    """
    url = (
        f"{BASE_API}/{pref_cd}/api/index.php"
        f"?kind=1&serviceTypeCode={service_code}"
        f"&page={page}&detail=0"
    )
    data = _fetch_json(url)
    if not data:
        # 別形式を試す
        url2 = (
            f"{BASE_API}/{pref_cd}/api/serviceType/{service_code}/list.json"
            f"?page={page}"
        )
        data = _fetch_json(url2)
    if not data:
        return []

    # レスポンス形式によって異なる
    if isinstance(data, list):
        return data
    for key in ["list", "jigyosho", "items", "result", "data"]:
        if key in data and isinstance(data[key], list):
            return data[key]
    return []


def _get_provider_detail(pref_cd: str, jigyosho_no: str) -> dict:
    """事業所詳細情報を取得（ウェブサイトURL・電話番号等）"""
    url = (
        f"{BASE_API}/{pref_cd}/api/index.php"
        f"?kind=2&jigyoshoNo={jigyosho_no}&serviceTypeCode=110"
    )
    data = _fetch_json(url)
    return data if isinstance(data, dict) else {}


def _extract_from_provider(item: dict) -> dict:
    """API レスポンスから必要フィールドを抽出（形式バリアント対応）"""
    result = {
        "company_name": "",
        "url": "",
        "phone": "",
        "address": "",
        "jigyosho_no": "",
    }

    # 事業所名
    for key in ["jigyoshoName", "name", "officeName", "service_name"]:
        if item.get(key):
            result["company_name"] = str(item[key]).strip()
            break

    # 事業所番号
    for key in ["jigyoshoNo", "no", "officeNo", "jigyosho_no"]:
        if item.get(key):
            result["jigyosho_no"] = str(item[key]).strip()
            break

    # ウェブサイト
    for key in ["homepageUrl", "url", "website", "hp"]:
        if item.get(key):
            url = str(item[key]).strip()
            if url.startswith("http"):
                result["url"] = url
            break

    # 電話番号
    for key in ["tel", "phone", "telNo"]:
        if item.get(key):
            result["phone"] = str(item[key]).strip()
            break

    # 住所
    for key in ["address", "addr", "jusho"]:
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
    parser = argparse.ArgumentParser(description="MHLW介護サービス情報からリード収集")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--prefs", type=str, default="",
                        help="カンマ区切りの都道府県コード (例: 13,27,14)")
    parser.add_argument("--pages", type=int, default=5, help="各都道府県で取得するページ数")
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

        for pref_cd in prefs:
            if found >= limit:
                break
            pref_str = f"{pref_cd:02d}"
            print(f"\n[都道府県 {pref_str}] スキャン中...")

            for service_code in SERVICE_CODES:
                for page in range(1, args.pages + 1):
                    if found >= limit:
                        break

                    providers = _get_providers_list(pref_str, service_code, page)
                    print(f"  [Page {page}] {service_code}: {len(providers)}件")

                    if not providers:
                        break

                    for item in providers:
                        if found >= limit:
                            break

                        info = _extract_from_provider(item)
                        company = info["company_name"]
                        if not company:
                            continue

                        url = info["url"]
                        email = ""

                        # URLがあればサイトからメール取得
                        if url:
                            html = _fetch_html(url)
                            if html:
                                emails = _emails_from_html(html)
                                if not emails:
                                    # contactページも試す
                                    base = url.rstrip("/")
                                    for path in ["/contact", "/inquiry", "/toiawase"]:
                                        h2 = _fetch_html(base + path)
                                        emails = _emails_from_html(h2)
                                        if emails:
                                            break
                                        time.sleep(0.3)
                                if emails:
                                    email = emails[0]
                            time.sleep(0.5)

                        # URLなし・メールなしの場合は詳細ページも試す
                        if not email and info.get("jigyosho_no"):
                            detail = _get_provider_detail(pref_str, info["jigyosho_no"])
                            if detail:
                                detail_info = _extract_from_provider(detail)
                                if detail_info["url"] and not url:
                                    url = detail_info["url"]
                                    html = _fetch_html(url)
                                    emails = _emails_from_html(html)
                                    if emails:
                                        email = emails[0]
                                    time.sleep(0.5)

                        if not email:
                            continue

                        if email in existing:
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
