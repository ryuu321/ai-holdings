"""
MHLW 介護サービス情報公表システムから汎用リード収集スクリプト（v2）
  python fetch_mhlw_leads.py --output path/to/leads.csv --service-codes 110 [--limit 100]

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
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE = "https://www.kaigokensaku.mhlw.go.jp"

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_PREFS = [13, 27, 14, 23, 11, 12, 1, 28, 40, 26, 34, 4, 22]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = [
    "noreply", "no-reply", "example", "sentry", "google",
    "schema.org", "w3.org", "placeholder", "test@", "mhlw.go.jp",
    "cloudflare", "amazonaws", "sendgrid", "form.jp",
]


def _new_opener() -> urllib.request.OpenerDirector:
    cjar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cjar))


def _fetch(opener: urllib.request.OpenerDirector, url: str,
           post_data: bytes | None = None,
           extra_headers: dict | None = None,
           timeout: int = 20) -> str:
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/json,*/*",
        "Accept-Language": "ja,en-US;q=0.7",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=post_data, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  fetch error {url[:70]}: {e}")
        return ""


def _init_session(opener: urllib.request.OpenerDirector,
                  pref_str: str, service_codes: list[str]) -> bool:
    """都道府県ページをGETしてPHPセッションを確立し、検索条件をセッションに保存"""
    top_url = f"{BASE}/{pref_str}/index.php"
    _fetch(opener, top_url)

    conditions = json.dumps({"ServiceTypeCode": service_codes, "CityCdList": [], "PrefCd": pref_str})
    post_body = urllib.parse.urlencode({
        "action_kouhyou_pref_search_list_list": "true",
        "method": "search",
        "PrefCd": pref_str,
        "FromPage": "kaigoTopPage",
        "SearchConditions": conditions,
        "SearchKeyword": "",
    }).encode("utf-8")

    html = _fetch(
        opener,
        f"{BASE}/{pref_str}/index.php",
        post_data=post_body,
        extra_headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": top_url,
        },
    )
    return 'data-type="search"' in html or "kaigoJigyosyoListPage" in html or len(html) > 10000


def _get_page(opener: urllib.request.OpenerDirector,
              pref_str: str, offset: int, count: int = 50) -> tuple[list[dict], int]:
    """AJAX JSON APIで1ページ分の事業所データを取得"""
    url = (
        f"{BASE}/{pref_str}/index.php"
        f"?action_kouhyou_pref_search_search=true&method=search"
        f"&p_count={count}&p_offset={offset}&p_sort_name=&p_order="
    )
    raw = _fetch(opener, url, extra_headers={
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, */*",
        "Referer": f"{BASE}/{pref_str}/index.php",
    })
    if not raw:
        return [], 0
    try:
        j = json.loads(raw)
        if j.get("status") == "success":
            total = j.get("pager", {}).get("total", 0)
            return j["data"], int(total)
    except Exception:
        pass
    return [], 0


def _emails_from_html(html: str) -> list[str]:
    found = EMAIL_RE.findall(html)
    result = []
    for e in found:
        e = e.lower().rstrip(".")
        if any(s in e for s in EMAIL_SKIP):
            continue
        ext = e.split(".")[-1].lower()
        if ext in {"png", "jpg", "gif", "svg", "pdf", "js", "css"}:
            continue
        local = e.split("@")[0]
        # 同一文字の連続（aaaaa@ など）はテスト用メールとして除外
        if any(local.count(c) > 4 for c in set(local)):
            continue
        if e not in result:
            result.append(e)
    return result[:2]


def _email_from_site(hp_url: str) -> str:
    if not hp_url or not hp_url.startswith("http"):
        return ""
    plain_opener = _new_opener()
    html = _fetch(plain_opener, hp_url, timeout=12)
    if html:
        emails = _emails_from_html(html)
        if emails:
            return emails[0]
        for path in ["/contact", "/inquiry", "/toiawase", "/about"]:
            h2 = _fetch(plain_opener, hp_url.rstrip("/") + path, timeout=10)
            emails = _emails_from_html(h2)
            if emails:
                return emails[0]
            time.sleep(0.3)
    return ""


def load_existing(leads_file: Path) -> set[str]:
    if not leads_file.exists():
        return set()
    with open(leads_file, encoding="utf-8", newline="") as f:
        return {row.get("email", "") for row in csv.DictReader(f) if row.get("email")}


def main():
    parser = argparse.ArgumentParser(description="MHLW介護サービス情報からリード収集（v2）")
    parser.add_argument("--output", required=True, help="出力 leads.csv パス")
    parser.add_argument("--service-codes", required=True,
                        help="カンマ区切りサービス種別コード (例: 110,113)")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--prefs", type=str, default="")
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
            print(f"\n[都道府県 {pref_str}] セッション初期化中...")

            opener = _new_opener()
            ok = _init_session(opener, pref_str, service_codes)
            if not ok:
                print(f"  セッション初期化失敗 → スキップ")
                continue

            offset = 0
            page_num = 0
            total_known = 0

            while found < limit:
                records, total = _get_page(opener, pref_str, offset)
                if total_known == 0 and total:
                    total_known = total
                print(f"  [P{page_num+1}] offset={offset}, {len(records)}件取得 (全{total_known}件)")
                if not records:
                    break

                new_on_page = 0
                for rec in records:
                    if found >= limit:
                        break

                    name = rec.get("JigyosyoName", "").strip()
                    if not name:
                        continue

                    hp_url = rec.get("JHPUrl", "").strip()
                    if not hp_url or not hp_url.startswith("http"):
                        continue

                    phone = rec.get("JigyosyoTel", "").strip()
                    address = rec.get("JigyosyoJyusho", "").strip()

                    email = _email_from_site(hp_url)
                    time.sleep(0.5)

                    if not email or email in existing:
                        if email:
                            print(f"  DUP: {email}")
                        continue

                    row = {
                        "company_name": name,
                        "email": email,
                        "url": hp_url,
                        "phone": phone,
                        "address": address,
                        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }
                    writer.writerow(row)
                    f.flush()
                    existing.add(email)
                    found += 1
                    new_on_page += 1
                    print(f"  [{found}] {name[:35]} | {email}")

                offset += len(records)
                page_num += 1

                if len(records) < 50:
                    break
                if total_known and offset >= total_known:
                    break

                time.sleep(1.5)

    print(f"\n完了: {found}件追加 → {leads_file}")


if __name__ == "__main__":
    main()
