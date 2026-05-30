"""
ウェブ検索（Yahoo Japan HTML / DuckDuckGo）ベースのリード収集スクリプト
Brave API の代替として全製品で使用可能。API キー不要。

  python fetch_web_leads.py --project sharotext --limit 50
  python fetch_web_leads.py --project taxtext --queries "税理士事務所 東京 メール" --limit 50

出力: saas-dev/projects/{project_dir}/outreach/leads.csv に追記
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

_ROOT = Path(__file__).parent.parent.parent.parent
CONFIG_DIR = _ROOT / "shared/gtm/config"

HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ja,en-US;q=0.7",
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "sentry", "google", "yahoo",
              "schema.org", "w3.org", "placeholder", "test@", "info@example",
              "cloudflare", "sentry.io", "amazonaws"]

# 検索クエリ展開用: プロジェクト設定から生成
PREFECTURES = ["東京", "大阪", "神奈川", "愛知", "埼玉", "千葉", "北海道", "兵庫",
               "福岡", "静岡", "茨城", "広島", "京都", "宮城", "新潟"]


def _load_config(project: str) -> dict:
    cfg_path = CONFIG_DIR / f"{project}.json"
    if not cfg_path.exists():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


def _fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS_HTML)
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
        if e.split(".")[-1].lower() in {"png", "jpg", "gif", "svg", "pdf", "zip", "js", "css"}:
            continue
        if e not in result:
            result.append(e)
    return result[:3]


def _yahoo_search(query: str, page: int = 1) -> list[dict]:
    """Yahoo Japan HTML検索結果からURLと会社名を取得"""
    b = (page - 1) * 10 + 1
    params = urllib.parse.urlencode({"p": query, "b": str(b), "ei": "UTF-8"})
    url = f"https://search.yahoo.co.jp/search?{params}"
    html = _fetch(url)
    if not html:
        return []

    results = []
    # 検索結果のタイトルとURLを抽出
    for match in re.finditer(
        r'<h3[^>]*>\s*<a[^>]+href="(https?://(?!search\.yahoo|yahoo\.co\.jp)[^"]+)"[^>]*>([^<]+)</a>',
        html, re.IGNORECASE
    ):
        link_url = match.group(1)
        title = re.sub(r'<[^>]+>', '', match.group(2)).strip()
        # リダイレクトURLを外す
        if "r.search.yahoo" in link_url or "search.yahoo" in link_url:
            continue
        if any(skip in link_url for skip in ["youtube", "twitter", "facebook",
                                              "instagram", "wikipedia", "indeed",
                                              "recruit", "mynavi", "townwork"]):
            continue
        results.append({"url": link_url, "title": title})

    return results[:10]


def _ddg_search(query: str) -> list[dict]:
    """DuckDuckGo HTML検索からURL取得（Yahoo失敗時のフォールバック）"""
    params = urllib.parse.urlencode({"q": query, "kl": "jp-jp"})
    url = f"https://html.duckduckgo.com/html/?{params}"
    html = _fetch(url)
    if not html:
        return []

    results = []
    for match in re.finditer(
        r'class="result__a"[^>]+href="(https?://[^"]+)"[^>]*>([^<]+)</a>',
        html, re.IGNORECASE
    ):
        link_url = match.group(1)
        title = match.group(2).strip()
        if any(skip in link_url for skip in ["youtube", "twitter", "facebook",
                                              "instagram", "wikipedia"]):
            continue
        results.append({"url": link_url, "title": title})

    return results[:10]


def _get_email_from_url(url: str) -> tuple[str, str]:
    """URLのページからメールアドレスを抽出。(email, company_name) を返す"""
    html = _fetch(url)
    if not html:
        return "", ""

    emails = _emails_from_html(html)
    # 会社名をog:site_nameかtitleから取得
    og_match = re.search(
        r'property=["\']og:site_name["\'][^>]+content=["\']([^"\']{2,50})["\']'
        r'|content=["\']([^"\']{2,50})["\'][^>]+property=["\']og:site_name["\']',
        html, re.IGNORECASE
    )
    title_match = re.search(r'<title[^>]*>([^|｜–\-<]{2,40})', html, re.IGNORECASE)
    company = ""
    if og_match:
        company = (og_match.group(1) or og_match.group(2) or "").strip()
    elif title_match:
        company = title_match.group(1).strip()

    if emails:
        return emails[0], company

    # contactページも試す
    for path in ["/contact", "/inquiry", "/toiawase", "/about"]:
        h2 = _fetch(url.rstrip("/") + path)
        emails = _emails_from_html(h2)
        if emails:
            return emails[0], company
        time.sleep(0.3)

    return "", company


def _build_queries(config: dict, custom_queries: list[str]) -> list[str]:
    """プロジェクト設定からクエリリストを生成"""
    if custom_queries:
        return custom_queries

    icp = config.get("icp", {})
    keywords = icp.get("target_keywords", [])
    name_hints = icp.get("company_name_hint_keywords", [])
    primary = keywords[:1] if keywords else name_hints[:1]
    if not primary:
        return []

    kw = primary[0]
    queries = []
    for pref in PREFECTURES[:8]:
        queries.append(f"{kw} {pref} メール お問い合わせ")
    for hint in name_hints[:3]:
        queries.append(f"{hint} 事務所 メールアドレス 問合")
    return queries


def main():
    parser = argparse.ArgumentParser(description="Yahoo Japan/DDGウェブ検索ベースのリード収集")
    parser.add_argument("--project", required=True, help="プロジェクト名 (例: taxtext)")
    parser.add_argument("--queries", type=str, default="",
                        help="カンマ区切りの検索クエリ (省略時は設定から自動生成)")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--delay", type=float, default=2.0, help="リクエスト間隔(秒)")
    args = parser.parse_args()

    config = _load_config(args.project)
    project_dir = config.get("project_dir", args.project)
    leads_file = _ROOT / f"saas-dev/projects/{project_dir}/outreach/leads.csv"
    leads_file.parent.mkdir(parents=True, exist_ok=True)

    custom_queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    queries = _build_queries(config, custom_queries)

    if not queries:
        print(f"クエリが生成できませんでした: {args.project}")
        return

    existing = set()
    if leads_file.exists():
        with open(leads_file, encoding="utf-8", newline="") as f:
            existing = {row.get("email", "") for row in csv.DictReader(f) if row.get("email")}
    print(f"既存リード: {len(existing)}件")

    write_header = not leads_file.exists()
    found = 0
    limit = args.limit

    with open(leads_file, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["company_name", "email", "url", "scraped_at"]
        )
        if write_header:
            writer.writeheader()

        for i, query in enumerate(queries):
            if found >= limit:
                break
            print(f"\n[Query {i+1}/{len(queries)}] {query}")

            # Yahoo Japan → DDG フォールバック
            results = _yahoo_search(query)
            if not results:
                time.sleep(1.0)
                results = _ddg_search(query)
            print(f"  {len(results)}件のURL取得")

            for item in results:
                if found >= limit:
                    break
                url = item["url"]
                email, company = _get_email_from_url(url)

                if not email or email in existing:
                    if email:
                        print(f"  DUP: {email}")
                    time.sleep(args.delay * 0.5)
                    continue

                if not company:
                    company = item.get("title", "")[:40]

                row = {
                    "company_name": company,
                    "email": email,
                    "url": url,
                    "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
                writer.writerow(row)
                f.flush()
                existing.add(email)
                found += 1
                print(f"  [{found}] {company[:30]} | {email}")
                time.sleep(args.delay)

            time.sleep(args.delay * 1.5)

    print(f"\n完了: {found}件追加 → {leads_file}")


if __name__ == "__main__":
    main()
