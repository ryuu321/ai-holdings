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
import urllib.robotparser
from pathlib import Path

_DIR = Path(__file__).parent
LEADS_FILE = _DIR / "leads.csv"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_DIR.parent.parent.parent.parent / ".env")
except ImportError:
    pass

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
    # 関東
    "不動産仲介 東京 賃貸 会社概要 お問い合わせ メール",
    "賃貸仲介 東京都 株式会社 contact info@",
    "不動産会社 埼玉 さいたま市 賃貸 お問い合わせ",
    "不動産仲介 千葉市 賃貸 株式会社 メールアドレス",
    "不動産仲介 横浜市 賃貸 株式会社 メールアドレス",
    "不動産仲介 川崎市 賃貸 contact メールアドレス",
    # 関西
    "不動産仲介 大阪市 賃貸 株式会社 メールアドレス",
    "賃貸仲介 京都市 不動産 株式会社 info@",
    "不動産仲介 神戸市 賃貸 メールアドレス お問い合わせ",
    "不動産会社 兵庫県 賃貸 株式会社 info@",
    "不動産仲介 奈良 賃貸 株式会社 メールアドレス",
    # 中部
    "不動産仲介 名古屋市 賃貸 株式会社 info@",
    "不動産会社 静岡 賃貸仲介 株式会社 メールアドレス",
    "不動産仲介 浜松 賃貸 株式会社 contact",
    "不動産会社 金沢 石川県 賃貸 info@",
    # 九州・中国
    "不動産仲介 福岡市 賃貸 株式会社 メールアドレス",
    "不動産会社 北九州 賃貸仲介 info@",
    "不動産仲介 広島市 賃貸 株式会社 info@",
    "不動産会社 岡山 賃貸仲介 株式会社 メールアドレス",
    # 北海道・東北
    "不動産仲介 仙台市 賃貸 株式会社 info@",
    "不動産会社 旭川 賃貸仲介 メールアドレス",
    # 一般
    "地域密着 不動産仲介 賃貸 株式会社 co.jp メールアドレス",
    "不動産会社 地元 賃貸管理 仲介 問い合わせメール",
    "賃貸不動産 中小企業 仲介 株式会社 info@",
    "不動産仲介 独立系 賃貸 株式会社 info@",
    "アパート賃貸 管理会社 仲介 株式会社 メールアドレス",
    "マンション賃貸 仲介 地域 株式会社 co.jp info@",
    "不動産屋 賃貸 地元 株式会社 info@",
    "住宅賃貸 仲介 株式会社 メールアドレス 問い合わせ",
    "賃貸物件 仲介業者 株式会社 info@ co.jp",
]

HEADERS_BASE = {
    # 正直なボット UA。robots.txt を尊重するため偽称しない
    "User-Agent": "FudoTextBot/1.0 (+mailto:ryuumg03@gmail.com)",
}

_robots_cache: dict = {}


def _can_fetch(url: str) -> bool:
    """robots.txt を確認してクロール許可かチェック。読み取り失敗は許可扱い。"""
    base = re.match(r"(https?://[^/]+)", url)
    if not base:
        return True
    origin = base.group(1)
    if origin in _robots_cache:
        rp = _robots_cache[origin]
        return rp.can_fetch(HEADERS_BASE["User-Agent"], url) if rp else True
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{origin}/robots.txt")
    try:
        rp.read()
        _robots_cache[origin] = rp
    except Exception:
        _robots_cache[origin] = None
        return True
    return rp.can_fetch(HEADERS_BASE["User-Agent"], url)


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

                # なければサイトを直接フェッチ（robots.txt 許可確認後）
                if not emails:
                    if not _can_fetch(site):
                        print(f"  robots.txt 拒否: {site}")
                        continue
                    html = _fetch_page(site)
                    emails = _emails_from_html(html)
                    # コンタクトページも試す
                    if not emails:
                        for path in ["/contact", "/inquiry", "/about"]:
                            contact_url = site.rstrip("/") + path
                            if not _can_fetch(contact_url):
                                continue
                            html2 = _fetch_page(contact_url)
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
