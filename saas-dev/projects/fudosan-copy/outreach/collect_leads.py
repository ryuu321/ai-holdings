"""
不動産会社リード収集スクリプト
入力: 会社URLリスト (urls.txt, 1行1URL)
出力: leads.csv (company_name, email, url, prefecture, scraped_at)

使い方:
  1. urls.txt に対象URLを貼り付ける（1行1件）
  2. python collect_leads.py を実行
  3. leads.csv が生成される
"""
import csv
import re
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

_DIR = Path(__file__).parent
URLS_FILE = _DIR / "urls.txt"
LEADS_FILE = _DIR / "leads.csv"

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)
BLACKLIST = ["example.com", "sentry.io", "google.com", "w3.org",
             "placeholder", "noreply", "no-reply", "support@gmail"]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FudoTextBot/1.0)"}


def _fetch(url: str, timeout: int = 10) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
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
        if any(b in e for b in BLACKLIST):
            continue
        if e not in result:
            result.append(e)
    return result[:3]  # 1社につき最大3件


def _extract_title(html: str) -> str:
    m = TITLE_RE.search(html)
    if m:
        return m.group(1).strip()[:60]
    return ""


def _contact_url(base: str) -> str:
    for path in ["/contact", "/inquiry", "/お問い合わせ", "/contact.html"]:
        yield base.rstrip("/") + path


def _load_existing() -> set[str]:
    if not LEADS_FILE.exists():
        return set()
    with open(LEADS_FILE, encoding="utf-8") as f:
        return {row["url"] for row in csv.DictReader(f)}


def main():
    if not URLS_FILE.exists():
        URLS_FILE.write_text("# 1行1URLで入力してください\n", encoding="utf-8")
        print(f"urls.txt を作成しました: {URLS_FILE}")
        return

    urls = [
        u.strip() for u in URLS_FILE.read_text(encoding="utf-8").splitlines()
        if u.strip() and not u.startswith("#")
    ]
    if not urls:
        print("urls.txt にURLを追加してください")
        return

    existing = _load_existing()
    new_urls = [u for u in urls if u not in existing]
    print(f"対象: {len(new_urls)}件（既存スキップ: {len(urls) - len(new_urls)}件）")

    write_header = not LEADS_FILE.exists()
    with open(LEADS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "email", "url", "scraped_at"])
        if write_header:
            writer.writeheader()

        for i, url in enumerate(new_urls, 1):
            print(f"  [{i}/{len(new_urls)}] {url[:60]}")
            html = _fetch(url)
            title = _extract_title(html)
            emails = _extract_emails(html)

            # コンタクトページも試す
            if not emails:
                for contact_url in _contact_url(url):
                    contact_html = _fetch(contact_url)
                    emails = _extract_emails(contact_html)
                    if emails:
                        break

            if emails:
                for email in emails:
                    writer.writerow({
                        "company_name": title,
                        "email": email,
                        "url": url,
                        "scraped_at": datetime.now().strftime("%Y-%m-%d"),
                    })
                f.flush()
                print(f"    メアド取得: {emails[0]}")
            else:
                print(f"    メアドなし → スキップ")

            time.sleep(1.5)  # 過負荷防止

    total = sum(1 for _ in open(LEADS_FILE, encoding="utf-8")) - 1
    print(f"\n完了。leads.csv 合計: {total}件")


if __name__ == "__main__":
    main()
