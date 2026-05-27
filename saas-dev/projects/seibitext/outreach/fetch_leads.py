"""
seibitext GTMリード収集スクリプト（Brave API）
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

_COMPANY_KEYWORDS = ['自動車', 'モータース', 'カー', '車検', '整備', '板金', '塗装', 'サービス', '修理']

QUERIES = ['自動車整備工場 お問い合わせ site:co.jp -求人', 'カーディーラー サービス部門 連絡先 site:co.jp -採用', '板金塗装工場 メールアドレス site:co.jp -転職', '車検専門店 問い合わせフォーム site:co.jp -アルバイト', '中古車販売 整備工場 連絡先 site:co.jp -募集', '自動車修理工場 サービス案内 site:co.jp -採用情報', 'ロードサービス 提携工場 連絡先 site:co.jp -協力会社', '認証工場 問い合わせ site:co.jp -リクルート', '指定工場 連絡先 site:co.jp -新卒', '整備士 募集 以外 お問い合わせ site:co.jp', '自動車点検 問い合わせ先 site:co.jp -求人', '自動車メンテナンス 連絡先 site:co.jp -採用', 'カーケアショップ 問い合わせ site:co.jp -パート', '地域名 自動車整備工場 連絡先 site:co.jp', '法人向け 自動車整備 問い合わせ site:co.jp']


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
                    company = _gemini_extract_company(html, url)
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



# ── Gemini会社名抽出フォールバック（_fix_fetch_leads.py により自動追加） ────────

def _gemini_extract_company(html: str, url: str = "") -> str:
    """
    Gemini Flash Lite で会社名を抽出。
    失敗時はドメイン名を返す（空文字を返さない保証）。
    """
    import json as _json
    import os as _os
    import re as _re
    from urllib.parse import urlparse as _urlparse

    gemini_key = _os.environ.get("GEMINI_API_KEY", "")

    # Gemini API 呼び出し
    if gemini_key and html:
        text = _re.sub(r"<[^>]+>", " ", html)
        text = _re.sub(r"\s+", " ", text).strip()[:1500]
        prompt = (
            f"以下はウェブサイト（{url}）のテキストです。\n"
            "このウェブサイトを運営している会社・事務所・法人の正式名称を1つだけ答えてください。\n"
            "「株式会社○○」「○○社会保険労務士事務所」「○○法人」のような形式で。\n"
            "わからない場合は「UNKNOWN」とだけ答えてください。余計な説明は不要です。\n\n"
            f"テキスト:\n{text}"
        )
        payload = _json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 30, "temperature": 0},
        }).encode()
        api_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash-lite:generateContent?key={gemini_key}"
        )
        try:
            import urllib.request as _req
            req = _req.Request(
                api_url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with _req.urlopen(req, timeout=15) as r:
                data = _json.loads(r.read())
            name = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            name = name.replace("「", "").replace("」", "").replace("*", "").strip()
            if 2 <= len(name) <= 40 and name != "UNKNOWN":
                return name
        except Exception:
            pass

    # ドメイン名フォールバック
    try:
        domain = _urlparse(url).netloc.lower()
        domain = _re.sub(r"^www\.", "", domain)
        domain = _re.sub(r"\.(co\.jp|or\.jp|ne\.jp|gr\.jp|com|jp|net|org|info)$", "", domain)
        if len(domain) >= 2:
            return domain
    except Exception:
        pass

    return "不明企業"

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=150)
    args = parser.parse_args()
    main(args.limit)
