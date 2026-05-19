"""
Brave Search APIで不動産会社メアドを収集
API: https://api.search.brave.com/res/v1/web/search
無料クレジット$5/月 = 約1650クエリ
"""
import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

_DIR = Path(__file__).parent
LEADS_FILE = _DIR / "leads.csv"

BRAVE_KEY = os.environ.get("BRAVE_API_KEY", "")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "sentry", "google",
              "schema.org", "w3.org", "placeholder", "sample@", "mail@mail",
              "abc@", "test@", "info@example"]
# 画像ファイルのアットマーク誤検知（@2x.png等）を除外するTLD
FAKE_TLDS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
             ".mp4", ".mov", ".pdf", ".zip"}
SITE_SKIP = ["suumo.jp", "homes.co.jp", "athome.co.jp", "chintai.net",
             "wikipedia", "google", "yahoo", "twitter", "facebook", "instagram"]

QUERIES = [
    "不動産仲介会社 東京 メールアドレス お問い合わせ",
    "不動産仲介会社 大阪 メールアドレス お問い合わせ",
    "不動産仲介会社 名古屋 メールアドレス",
    "不動産仲介会社 福岡 メールアドレス",
    "不動産仲介会社 横浜 メールアドレス",
    "不動産仲介会社 札幌 メールアドレス",
    "不動産仲介会社 神戸 メールアドレス",
    "宅建業者 東京 会社 メールアドレス",
    "宅建業者 大阪 会社 メールアドレス",
    "不動産会社 賃貸 東京 info@ OR contact@ site:co.jp",
    "不動産会社 売買 東京 メールアドレス site:co.jp",
    "不動産会社 埼玉 メールアドレス お問い合わせ",
    "不動産会社 千葉 メールアドレス お問い合わせ",
    "不動産会社 愛知 メールアドレス お問い合わせ",
    "不動産会社 兵庫 メールアドレス",
]

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def _brave_search(query: str) -> list[dict]:
    if not BRAVE_KEY:
        print("BRAVE_API_KEY未設定")
        return []
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.search.brave.com/res/v1/web/search?q={encoded}&count=20&country=JP"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "X-Subscription-Token": BRAVE_KEY,
        })
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("web", {}).get("results", [])
    except Exception as e:
        print(f"  Brave検索失敗: {e}")
        return []


def _fetch_page(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS_BASE)
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read(1024 * 150)
            enc = r.headers.get_content_charset("utf-8")
            return raw.decode(enc, errors="ignore")
    except Exception:
        return ""


def _emails_from_html(html: str) -> list[str]:
    found = EMAIL_RE.findall(html)
    result = []
    for e in found:
        e = e.lower().rstrip(".")
        if any(s in e for s in EMAIL_SKIP):
            continue
        # 画像ファイル誤検知を除外（@の後がドメインではなくファイル拡張子）
        domain = e.split("@")[-1] if "@" in e else ""
        if any(domain.endswith(ext) for ext in FAKE_TLDS):
            continue
        if e not in result:
            result.append(e)
    return result[:2]


def _load_existing() -> set[str]:
    if not LEADS_FILE.exists():
        return set()
    with open(LEADS_FILE, encoding="utf-8") as f:
        return {row["email"] for row in csv.DictReader(f)}


def main():
    print("[fetch_leads] Brave Search APIでリード収集開始")
    existing = _load_existing()
    print(f"既存: {len(existing)}件")

    new_count = 0
    seen_urls = set()

    write_header = not LEADS_FILE.exists()
    with open(LEADS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "email", "url"])
        if write_header:
            writer.writeheader()

        for qi, query in enumerate(QUERIES, 1):
            print(f"\n[{qi}/{len(QUERIES)}] {query[:50]}")
            results = _brave_search(query)
            print(f"  検索結果: {len(results)}件")

            for r in results:
                url = r.get("url", "")
                title = r.get("title", "")
                desc = r.get("description", "")

                if not url or any(s in url for s in SITE_SKIP):
                    continue

                base = re.match(r"(https?://[^/]+)", url)
                site = base.group(1) + "/" if base else url
                if site in seen_urls:
                    continue
                seen_urls.add(site)

                # 検索結果のdescriptionからまずメアドを探す
                emails = _emails_from_html(desc + " " + title)

                # なければサイトを直接フェッチ
                if not emails:
                    html = _fetch_page(site)
                    emails = _emails_from_html(html)
                    # コンタクトページも試す
                    if not emails:
                        for path in ["/contact", "/inquiry", "/about"]:
                            html2 = _fetch_page(site.rstrip("/") + path)
                            emails = _emails_from_html(html2)
                            if emails:
                                break
                    time.sleep(1.0)

                for email in emails:
                    if email in existing:
                        continue
                    writer.writerow({
                        "company_name": title or site,
                        "email": email,
                        "url": site,
                    })
                    f.flush()
                    existing.add(email)
                    new_count += 1
                    print(f"  取得: {email} / {title[:30]}")

            time.sleep(2)

    print(f"\n完了。新規リード: {new_count}件 / leads.csv合計: {len(existing)}件")


if __name__ == "__main__":
    main()
