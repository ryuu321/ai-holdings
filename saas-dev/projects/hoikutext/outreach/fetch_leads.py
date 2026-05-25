"""
hoikutext GTMリード収集スクリプト（Brave API）
  python fetch_leads.py [--limit 150]
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
    r'<meta[^>]+property=["\'"]og:site_name["\'"][^>]+content=["\'"]([^"\' ]{2,40})["\'"]'
    r'|<meta[^>]+content=["\'"]([^"\' ]{2,40})["\'"][^>]+property=["\'"]og:site_name["\'"]',
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)

EMAIL_SKIP = ["noreply", "no-reply", "example", "sentry", "google",
              "schema.org", "w3.org", "placeholder", "sample@", "test@",
              "@sample.", "@mail.jp", "@example.", "postmaster@", "webmaster@"]
FAKE_TLDS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".pdf", ".zip"}
SITE_SKIP = ["wikipedia", "google", "yahoo", "twitter", "facebook", "instagram",
             "amazon", "rakuten", "mynavi", "doda", "rikunabi", "indeed",
             "townwork", "hellowork", "nikkei", "nhk", "pref.", "city.", "go.jp"]

_COMPANY_KEYWORDS = ['社会福祉法人', '学校法人', '幼保連携型', '地域型保育', '企業主導型']

QUERIES = ['認定こども園 info@', '幼稚園 メールでのお問い合わせ', '社会福祉法人 保育園 連絡先', '学校法人 幼稚園 連絡先', '地域名 保育園 問い合わせ', '地域名 認定こども園 メールアドレス', '保育施設 運営会社 お問い合わせ', '保育園 事務長 メール', '保育園 採用担当 連絡先', '保育園 施設長 問い合わせ', '保育園 事務局 連絡先', '企業主導型保育園 お問い合わせ', '小規模保育事業所 連絡先']


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
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; TextSeriesBot/1.0)"})
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
    return fallback[:40] if fallback else ""


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
