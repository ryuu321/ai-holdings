"""
宅建業者リードをMLIT etsuran + Brave APIで収集
  python fetch_mlit_leads.py

2段階方式:
  Phase 1: MLIT etsuranから会社名・免許番号を取得（確実な宅建業者リスト）
  Phase 2: 会社名をBrave APIで検索して公式サイトとメールアドレスを取得

Phase 1がMLITのHTML構造変更等で失敗した場合は、
改善済みBrave直接クエリ（会社名キーワード強制・ネガティブKW付き）にフォールバック。
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
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
OG_SITE_RE = re.compile(
    r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']{2,40})["\']'
    r'|<meta[^>]+content=["\']([^"\']{2,40})["\'][^>]+property=["\']og:site_name["\']',
    re.IGNORECASE,
)
TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)

EMAIL_SKIP = ["noreply", "no-reply", "example", "sentry", "google",
              "schema.org", "w3.org", "placeholder", "sample@", "mail@mail",
              "abc@", "test@", "info@example", "@sample.", "@mail.jp", "@mail.com",
              "@example.", "postmaster@", "webmaster@", "admin@"]
FAKE_TLDS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
             ".mp4", ".mov", ".pdf", ".zip"}
SITE_SKIP = ["suumo.jp", "homes.co.jp", "athome.co.jp", "chintai.net",
             "wikipedia", "google", "yahoo", "twitter", "facebook", "instagram",
             "minkabu", "rakuten", "amazon", "tabelog", "hotpepper"]
_COMPANY_KEYWORDS = ["株式会社", "有限会社", "合同会社", "一般社団法人"]

# MLITのetsuranシステム
MLIT_ETSURAN_URL = "https://etsuran.mlit.go.jp/TAKKEN/takkenKensaku.do"

# 都道府県コードとターゲット順（人口・不動産市場規模順）
MLIT_KEN_CODES = [
    13,  # 東京
    27,  # 大阪
    14,  # 神奈川
    23,  # 愛知
    11,  # 埼玉
    12,  # 千葉
    1,   # 北海道
    28,  # 兵庫
    40,  # 福岡
    26,  # 京都
    34,  # 広島
    4,   # 宮城
    22,  # 静岡
]

# 改善済みBrave直接クエリ（フォールバック用）
# 変更点: "株式会社"必須・ネガティブキーワード追加・co.jp指定
FALLBACK_QUERIES = [
    '"株式会社" 不動産仲介 賃貸 東京都 co.jp -suumo -athome -homes -ランキング',
    '"株式会社" 不動産仲介 賃貸 大阪市 co.jp -suumo -athome -ランキング',
    '"株式会社" 賃貸仲介 神奈川県 co.jp -suumo -homes -比較',
    '"株式会社" 不動産仲介 愛知県 名古屋 co.jp -ランキング -athome',
    '"株式会社" 不動産仲介 福岡市 賃貸 co.jp -suumo -まとめ',
    '"株式会社" 賃貸仲介 埼玉県 さいたま市 co.jp -ランキング',
    '"株式会社" 不動産仲介 千葉市 賃貸 co.jp -suumo',
    '"株式会社" 不動産仲介 札幌市 賃貸 co.jp -ランキング',
    '"有限会社" 不動産仲介 賃貸 東京 co.jp',
    '"株式会社" 賃貸仲介 横浜市 co.jp -比較 -まとめ',
    '"株式会社" 不動産仲介 広島市 賃貸 co.jp',
    '"株式会社" 賃貸仲介 仙台市 co.jp -ランキング',
    '"株式会社" 不動産 賃貸仲介 京都市 co.jp',
    '"株式会社" 不動産仲介 神戸市 賃貸 co.jp',
    '"株式会社" 賃貸仲介 静岡市 co.jp',
]

HEADERS_BASE = {
    "User-Agent": "FudoTextBot/1.0 (+mailto:ryuumg03@gmail.com)",
}

_robots_cache: dict = {}

_STRIP_TAGS = re.compile(r"<[^>]+>")
_COLLAPSE_WS = re.compile(r"\s+")


def _html_to_text(html: str, max_chars: int = 1200) -> str:
    text = _STRIP_TAGS.sub(" ", html)
    return _COLLAPSE_WS.sub(" ", text).strip()[:max_chars]


def _is_fudosan_ai(html: str) -> bool:
    """ページ内容をGeminiで判定。不動産仲介業でなければFalseを返す。"""
    if not GEMINI_KEY:
        return True
    text = _html_to_text(html)
    prompt = (
        "以下はある会社のウェブサイトのテキストです。"
        "この会社が「不動産仲介・賃貸仲介・売買仲介・物件管理」などの"
        "不動産仲介事業を主な事業として行っているかどうかを判定してください。\n\n"
        f"---\n{text}\n---\n\n"
        "不動産仲介企業なら「YES」、そうでなければ「NO」とだけ答えてください。"
    )
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 5, "temperature": 0}
    }).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={GEMINI_KEY}"
    try:
        req = urllib.request.Request(url, data=payload,
                                      headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        answer = data["candidates"][0]["content"]["parts"][0]["text"].strip().upper()
        return answer.startswith("YES")
    except Exception:
        return True


def _can_fetch(url: str) -> bool:
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


def _brave_search(query: str, count: int = 20) -> list[dict]:
    if not BRAVE_KEY:
        print("BRAVE_API_KEY未設定")
        return []
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.search.brave.com/res/v1/web/search?q={encoded}&count={count}&country=JP"
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
        domain = e.split("@")[-1] if "@" in e else ""
        if any(domain.endswith(ext) for ext in FAKE_TLDS):
            continue
        if e not in result:
            result.append(e)
    return result[:2]


def _extract_company_name(html: str, fallback_title: str = "") -> str:
    """og:site_name優先で会社名を抽出。法人格なしは空文字を返す。"""
    m = OG_SITE_RE.search(html)
    if m:
        name = (m.group(1) or m.group(2) or "").strip()
        if name and any(kw in name for kw in _COMPANY_KEYWORDS):
            return name[:40]
    t = TITLE_RE.search(html)
    title = t.group(1).strip() if t else fallback_title.strip()
    if title:
        for sep in ["｜", "|", "–", "-", "—", "　"]:
            if sep not in title:
                continue
            for part in title.split(sep):
                part = part.strip()
                if any(kw in part for kw in _COMPANY_KEYWORDS) and len(part) <= 30:
                    return part
    return ""


def _fetch_mlit_companies(ken_code: int, count: int = 100) -> list[str]:
    """
    MLIT etsuranから宅建業者の会社名リストを取得。
    取得失敗時は空リストを返す（呼び出し側でフォールバック処理）。
    """
    url = (
        f"{MLIT_ETSURAN_URL}"
        f"?kenCode={ken_code:02d}&dispCount={count}"
        f"&sv_licenseNoFrom=&sv_licenseNoTo="
    )
    try:
        req = urllib.request.Request(url, headers=HEADERS_BASE)
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(1024 * 1024)
            enc = r.headers.get_content_charset("utf-8")
            html = raw.decode(enc, errors="ignore")
    except Exception as e:
        print(f"  MLIT取得失敗 (ken={ken_code:02d}): {e}")
        return []

    companies = []
    # テーブルセルから法人名を抽出（先頭・中間・末尾どこでも可）
    for m in re.finditer(
        r'<td[^>]*>([^<]{0,20}(?:株式会社|有限会社|合同会社)[^<]{0,20})</td>',
        html
    ):
        name = m.group(1).strip()
        if name and len(name) <= 40 and name not in companies:
            companies.append(name)

    return companies[:count]


def _find_company_email(company_name: str) -> tuple[str, str, str]:
    """
    会社名からBrave検索→公式サイト→メールアドレスを返す。
    戻り値: (email, url, actual_company_name) — 取得失敗時は ("", "", "")
    """
    query = f'"{company_name}" 公式 メール OR お問い合わせ site:co.jp OR site:.jp'
    results = _brave_search(query, count=5)
    time.sleep(0.5)

    for r in results:
        url = r.get("url", "")
        if not url or any(s in url for s in SITE_SKIP):
            continue
        base = re.match(r"(https?://[^/]+)", url)
        if not base:
            continue
        site = base.group(1) + "/"

        if not _can_fetch(site):
            continue
        html = _fetch_page(site)
        emails = _emails_from_html(html)
        extracted_name = _extract_company_name(html, company_name)

        if not emails:
            for path in ["/contact", "/inquiry", "/about"]:
                contact_url = site.rstrip("/") + path
                if not _can_fetch(contact_url):
                    continue
                html2 = _fetch_page(contact_url)
                emails = _emails_from_html(html2)
                if emails:
                    if not extracted_name:
                        extracted_name = _extract_company_name(html2, company_name)
                    break
            time.sleep(1.0)

        if emails:
            name = extracted_name or company_name
            return emails[0], site, name

    return "", "", ""


def _load_existing() -> set[str]:
    if not LEADS_FILE.exists():
        return set()
    with open(LEADS_FILE, encoding="utf-8") as f:
        return {row["email"] for row in csv.DictReader(f)}


def _process_brave_results(results: list[dict], existing: set[str],
                            writer, f) -> int:
    """Brave検索結果からリードを抽出してCSVに追記。新規追加件数を返す。"""
    added = 0
    seen_sites = set()
    for r in results:
        url = r.get("url", "")
        title = r.get("title", "")
        desc = r.get("description", "")

        if not url or any(s in url for s in SITE_SKIP):
            continue
        base = re.match(r"(https?://[^/]+)", url)
        if not base:
            continue
        # co.jp / .jp ドメインを優先（それ以外はスキップ）
        domain = base.group(1)
        if not (domain.endswith(".co.jp") or domain.endswith(".jp")):
            continue
        site = domain + "/"
        if site in seen_sites:
            continue
        seen_sites.add(site)

        emails = _emails_from_html(desc + " " + title)
        company_name = ""
        page_html = ""
        if not emails:
            if not _can_fetch(site):
                continue
            page_html = _fetch_page(site)
            emails = _emails_from_html(page_html)
            company_name = _extract_company_name(page_html, title)
            if not emails or not company_name:
                for path in ["/contact", "/inquiry", "/about"]:
                    cu = site.rstrip("/") + path
                    if not _can_fetch(cu):
                        continue
                    html2 = _fetch_page(cu)
                    if not emails:
                        emails = _emails_from_html(html2)
                    if not company_name:
                        company_name = _extract_company_name(html2)
                    if emails and company_name:
                        break
            time.sleep(1.0)
        else:
            company_name = _extract_company_name("", title)

        # 法人格なしはスキップ
        if not company_name or not any(kw in company_name for kw in _COMPANY_KEYWORDS):
            continue

        # Geminiで不動産仲介業か判定（Phase 2のみ・MLITは国が保証済みなので不要）
        if page_html and not _is_fudosan_ai(page_html):
            print(f"  - SKIP（不動産仲介業外・AI判定）: {company_name[:30]}")
            time.sleep(0.3)
            continue

        for email in emails:
            if email in existing:
                continue
            writer.writerow({"company_name": company_name, "email": email, "url": site})
            f.flush()
            existing.add(email)
            added += 1
            print(f"  取得: {company_name[:25]} | {email}")
    return added


def main():
    print("[fetch_leads] MLIT + Brave APIでリード収集開始")
    existing = _load_existing()
    print(f"既存: {len(existing)}件")

    new_count = 0
    write_header = not LEADS_FILE.exists()

    with open(LEADS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "email", "url"])
        if write_header:
            writer.writeheader()

        # ─── Phase 1: MLIT → Brave の2段階収集 ───
        print("\n=== Phase 1: MLIT etsuran → 会社名取得 ===")
        mlit_success = False
        for ken_code in MLIT_KEN_CODES:
            print(f"\n  都道府県コード {ken_code:02d} ...")
            companies = _fetch_mlit_companies(ken_code, count=50)
            if not companies:
                continue
            mlit_success = True
            print(f"  {len(companies)}社取得 → Braveでメール検索")

            for i, company in enumerate(companies, 1):
                email, site, name = _find_company_email(company)
                if not email or email in existing:
                    continue
                writer.writerow({"company_name": name or company, "email": email, "url": site})
                f.flush()
                existing.add(email)
                new_count += 1
                print(f"    [{i}] {(name or company)[:25]} | {email}")
                time.sleep(2)

        # ─── Phase 2: Brave直接クエリ（フォールバック or 補完） ───
        label = "補完" if mlit_success else "フォールバック"
        print(f"\n=== Phase 2: Brave直接クエリ（{label}） ===")
        for qi, query in enumerate(FALLBACK_QUERIES, 1):
            print(f"\n[{qi}/{len(FALLBACK_QUERIES)}] {query[:60]}")
            results = _brave_search(query)
            print(f"  検索結果: {len(results)}件")
            added = _process_brave_results(results, existing, writer, f)
            new_count += added
            time.sleep(2)

    print(f"\n完了。新規リード: {new_count}件 / leads.csv合計: {len(existing)}件")


if __name__ == "__main__":
    main()
