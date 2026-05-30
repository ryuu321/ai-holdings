"""
全国都道府県社会保険労務士会ディレクトリからリードを収集
各都道府県SR会の会員検索ページをスクレイプ。

  python fetch_pref_sr_leads.py [--limit 200] [--prefs osaka,kanagawa,aichi]

出力: leads.csv に追記 (company_name, email, url, phone, address, scraped_at)
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

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "google", "schema.org",
              "w3.org", "test@", "sharou.or.jp", "sr.or.jp"]

# 各都道府県SR会の会員検索URL
# 形式: (pref_name, base_url, search_path, page_param)
PREF_SR_SITES = [
    ("大阪", "https://www.osaka-sr.or.jp", "/member/search/", "page"),
    ("神奈川", "https://www.kanagawa-sr.or.jp", "/office/", "page"),
    ("愛知", "https://www.aichi-sr.com", "/membership/search/", "page"),
    ("埼玉", "https://www.saitama-sr.or.jp", "/jimusho/search/", "page"),
    ("兵庫", "https://www.hyogo-sr.com", "/member/", "page"),
    ("福岡", "https://www.fukuoka-sr.or.jp", "/member/search/", "page"),
    ("北海道", "https://www.hokkaido-sr.or.jp", "/member/", "page"),
    ("静岡", "https://www.shizuoka-sr.or.jp", "/member/search/", "page"),
    ("広島", "https://www.hiroshima-sr.or.jp", "/member/", "page"),
    ("京都", "https://www.kyoto-sr.or.jp", "/member/", "page"),
]


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


def _extract_offices(html: str, base_url: str) -> list[dict]:
    """HTMLから事務所情報（名前・メール・URL）を抽出"""
    offices = []
    CORP_KW = ["社会保険労務士", "SR", "sr", "事務所", "法人"]

    # メールアドレスを直接探す
    emails = _emails_from_html(html)

    # 会社名を探す（法人格 or 社労士キーワード含む）
    name_patterns = [
        r'<(?:td|th|div|li|h[1-6])[^>]*>([^<]{3,50}(?:社会保険労務士|SR法人|労務)[^<]{0,30})</(?:td|th|div|li|h[1-6])>',
        r'class="[^"]*(?:name|company|jimusho)[^"]*"[^>]*>([^<]{3,50})</[^>]+>',
        r'<(?:td|div)[^>]*>([^<]{2,40}(?:事務所|法人|オフィス)[^<]{0,20})</(?:td|div)>',
    ]
    company_name = ""
    for pat in name_patterns:
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            company_name = m.group(1).strip()
            break

    # 詳細ページリンクを探す
    detail_links = re.findall(
        r'href="(/(?:member|office|jimusho|profile)[^"]{0,100})"', html
    )

    for email in emails:
        offices.append({
            "company_name": company_name,
            "email": email,
            "url": base_url if not detail_links else base_url + detail_links[0],
        })

    return offices


def _scrape_list_page(url: str, base_url: str) -> list[dict]:
    """一覧ページから各事務所の情報を抽出"""
    html = _fetch(url)
    if not html:
        return []

    offices = []
    CORP_KW = ["社会保険労務士", "事務所", "法人", "SR"]

    # 各行・各ブロックを解析
    blocks = re.split(r'(?=<(?:tr|div|li)[^>]*(?:member|office|row|item)[^>]*>)', html, flags=re.IGNORECASE)
    if len(blocks) < 3:
        # フォールバック: メールアドレス直抽出
        emails = _emails_from_html(html)
        rows = html.split("<tr")
        for row in rows:
            emails_in_row = _emails_from_html(row)
            if not emails_in_row:
                continue
            name_m = re.search(
                r'<td[^>]*>([^<]{3,50}(?:社会保険労務士|SR|事務所|法人)[^<]{0,30})</td>',
                row, re.IGNORECASE
            ) or re.search(r'<td[^>]*>([^<]{4,50})</td>', row)
            name = name_m.group(1).strip() if name_m else ""
            for e in emails_in_row:
                offices.append({"company_name": name, "email": e, "url": url})
        return offices

    for block in blocks[1:]:
        emails = _emails_from_html(block)
        if not emails:
            continue
        name_m = re.search(
            r'<(?:td|div|span)[^>]*>([^<]{3,50}(?:社会保険労務士|事務所|法人|SR)[^<]{0,30})</(?:td|div|span)>',
            block, re.IGNORECASE
        ) or re.search(r'<(?:td|div)[^>]*>([^<]{4,50})</(?:td|div)>', block)
        name = name_m.group(1).strip() if name_m else ""
        for e in emails:
            offices.append({"company_name": name, "email": e, "url": url})

    return offices


def load_existing() -> set[str]:
    if not LEADS_FILE.exists():
        return set()
    with open(LEADS_FILE, encoding="utf-8", newline="") as f:
        return {row.get("email", "") for row in csv.DictReader(f) if row.get("email")}


def main():
    parser = argparse.ArgumentParser(description="全国都道府県社労士会ディレクトリからリード収集")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--pages", type=int, default=10, help="各都道府県の最大ページ数")
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()

    existing = load_existing()
    print(f"既存リード: {len(existing)}件")

    write_header = not LEADS_FILE.exists()
    found = 0
    limit = args.limit

    with open(LEADS_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["company_name", "email", "url", "phone", "address", "scraped_at"]
        )
        if write_header:
            writer.writeheader()

        for pref_name, base_url, search_path, page_param in PREF_SR_SITES:
            if found >= limit:
                break
            print(f"\n[{pref_name}] {base_url}{search_path}")

            for page in range(1, args.pages + 1):
                if found >= limit:
                    break

                # ページURLを組み立て
                if page == 1:
                    page_url = base_url + search_path
                else:
                    page_url = f"{base_url}{search_path}?{page_param}={page}"

                offices = _scrape_list_page(page_url, base_url)
                print(f"  [Page {page}] {len(offices)}件検出")

                if not offices:
                    break

                new_count = 0
                for o in offices:
                    if found >= limit:
                        break
                    email = o.get("email", "").lower()
                    if not email or email in existing:
                        continue
                    existing.add(email)
                    writer.writerow({
                        "company_name": o.get("company_name", ""),
                        "email": email,
                        "url": o.get("url", base_url),
                        "phone": "",
                        "address": pref_name,
                        "scraped_at": datetime.now().strftime("%Y-%m-%d"),
                    })
                    found += 1
                    new_count += 1

                if new_count == 0:
                    print(f"  新規なし → {pref_name}終了")
                    break

                time.sleep(args.delay)

    print(f"\n完了: {found}件追加 → {LEADS_FILE}")


if __name__ == "__main__":
    main()
