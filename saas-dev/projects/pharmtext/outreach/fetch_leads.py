"""
調剤薬局リードをBrave APIで収集
  python fetch_leads.py [--limit 100]

出力: leads.csv (company_name, email, url, prefecture, scraped_at)
"""
import csv
import json
import os
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
    except (AttributeError, Exception):
        pass

_DIR = Path(__file__).parent
LEADS_FILE = _DIR / "leads.csv"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_DIR.parent.parent.parent.parent / ".env")
except ImportError:
    pass

BRAVE_KEY = os.environ.get("BRAVE_API_KEY", "")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
OG_SITE_RE = re.compile(
    r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']{2,40})["\']'
    r'|<meta[^>]+content=["\']([^"\']{2,40})["\'][^>]+property=["\']og:site_name["\']',
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)

EMAIL_SKIP = ["noreply", "no-reply", "example", "sentry", "google",
              "schema.org", "w3.org", "placeholder", "sample@", "test@",
              "@sample.", "@mail.jp", "@example.", "postmaster@", "webmaster@"]
FAKE_TLDS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".pdf", ".zip"}
SITE_SKIP = ["wikipedia", "google", "yahoo", "twitter", "facebook", "instagram",
             "amazon", "rakuten", "mynavi", "doda", "rikunabi", "indeed",
             "townwork", "hellowork", "nikkei", "nhk", "pref.", "city.", "go.jp",
             "yakkyokudb", "pharmadb", "kusuri"]

_COMPANY_KEYWORDS = ["薬局", "ファーマシー", "調剤", "ドラッグ", "pharmacy"]

QUERIES = [
    '調剤薬局 "お問い合わせ" site:co.jp -求人',
    '薬局 "メールでのお問い合わせ" -採用 -求人',
    '調剤薬局 "info@" site:co.jp -ランキング',
    '薬局 "お問い合わせ" 薬剤師 -一覧 -比較',
    '調剤薬局 "contact@" site:co.jp',
    '薬局 服薬指導 "メール" -求人 -ランキング',
    '調剤薬局 東京 "お問い合わせ" site:co.jp -求人',
    '薬局 大阪 "info@" -採用',
    '調剤薬局 名古屋 "メール" site:co.jp',
    '薬局 神奈川 "お問い合わせ" -求人',
    '調剤薬局 福岡 "contact@" site:co.jp',
    '薬局 埼玉 "info@" -採用 -一覧',
    '調剤薬局 在宅医療 "お問い合わせ" site:co.jp',
    '薬局 管理薬剤師 "メール" -求人',
    '調剤薬局 漢方 "お問い合わせ" -ランキング',
    '薬局 健康相談 "info@" site:co.jp',
    '調剤薬局 ジェネリック "メールアドレス" -求人',
    '薬局 "ご連絡" "メール" site:co.jp -まとめ',
    '調剤薬局 地域密着 "お問い合わせ" -一覧',
    'ファーマシー "お問い合わせ" site:co.jp -求人',
]


def _brave_search(query: str, count: int = 10) -> list[dict]:
    if not BRAVE_KEY:
        return []
    url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}&count={count}&country=jp"
    try:
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_KEY,
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return data.get("web", {}).get("results", [])
    except Exception as e:
        print(f"  Brave API エラー: {e}")
        return []


def _fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; PharmTextBot/1.0)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read()
            enc = r.headers.get_content_charset("utf-8")
            return raw.decode(enc, errors="ignore")
    except Exception:
        return ""


def _extract_emails(html: str) -> list[str]:
    found = EMAIL_RE.findall(html)
    result = []
    for e in found:
        e = e.lower()
        if any(b in e for b in EMAIL_SKIP):
            continue
        if any(e.endswith(t) for t in FAKE_TLDS):
            continue
        if e not in result:
            result.append(e)
    return result[:2]


def _extract_company_name(html: str, fallback: str = "") -> str:
    m = OG_SITE_RE.search(html)
    if m:
        name = (m.group(1) or m.group(2) or "").strip()
        if name and any(kw in name for kw in _COMPANY_KEYWORDS):
            return name[:40]
    t = TITLE_RE.search(html)
    if t:
        title = t.group(1).strip()
        for sep in ["｜", "|", "–", "-", "—", "　"]:
            parts = title.split(sep)
            if len(parts) == 1:
                continue
            for part in parts:
                part = part.strip()
                if any(kw in part for kw in _COMPANY_KEYWORDS) and len(part) <= 30:
                    return part
    return ""


def main(limit: int = 150):
    if not BRAVE_KEY:
        print("BRAVE_API_KEY が未設定です。.envに追加してください。")
        return

    existing = set()
    if LEADS_FILE.exists():
        with open(LEADS_FILE, encoding="utf-8") as f:
            existing = {row["url"] for row in csv.DictReader(f)}
    print(f"既存リード: {len(existing)}件")

    write_header = not LEADS_FILE.exists()
    collected = 0

    with open(LEADS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "email", "url", "prefecture", "scraped_at"])
        if write_header:
            writer.writeheader()

        for query in QUERIES:
            if collected >= limit:
                break
            print(f"\nクエリ: {query[:60]}...")
            results = _brave_search(query, count=10)
            time.sleep(1.0)

            for r in results:
                if collected >= limit:
                    break
                url = r.get("url", "")
                if not url or any(s in url for s in SITE_SKIP):
                    continue
                if url in existing:
                    continue

                html = _fetch_html(url)
                if not html:
                    time.sleep(0.5)
                    continue

                emails = _extract_emails(html)
                if not emails:
                    for path in ["/contact", "/inquiry", "/contact.html"]:
                        from urllib.parse import urlparse
                        base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                        contact_html = _fetch_html(base + path)
                        if contact_html:
                            emails = _extract_emails(contact_html)
                            if emails:
                                break
                        time.sleep(0.3)

                if not emails:
                    existing.add(url)
                    continue

                company = _extract_company_name(html, r.get("title", ""))
                if not company:
                    existing.add(url)
                    continue

                for email in emails:
                    writer.writerow({
                        "company_name": company,
                        "email": email,
                        "url": url,
                        "prefecture": "",
                        "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })
                    f.flush()
                    print(f"  + {company[:30]} | {email}")

                existing.add(url)
                collected += 1
                time.sleep(1.0)

    print(f"\n完了。{collected}件収集しました -> {LEADS_FILE}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=150)
    args = parser.parse_args()
    main(args.limit)
