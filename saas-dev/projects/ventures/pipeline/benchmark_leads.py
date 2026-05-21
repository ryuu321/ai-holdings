"""
業種別リード取得率ベンチマーク
  python benchmark_leads.py

各業種について Brave API で実際に検索し、
メール取得率・ドメイン品質を計測してスコアを補正する。
"""
import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).parent.parent.parent.parent.parent / ".env")
except ImportError:
    pass

BRAVE_KEY = os.environ.get("BRAVE_API_KEY", "")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
EMAIL_SKIP = ["noreply", "no-reply", "example", "sentry", "google", "schema.org",
              "w3.org", "placeholder", "sample@", "test@", "@sample.", "@mail.jp",
              "@example.", "postmaster@", "webmaster@"]
FAKE_TLDS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".pdf", ".zip"}
GOOD_DOMAINS = ["co.jp", "jp", "or.jp", "ne.jp"]
BAD_DOMAINS  = ["gmail.com", "yahoo.co.jp", "hotmail.com", "outlook.com", "outlook.jp"]

INDUSTRIES = [
    {
        "name": "電気工事業者",
        "rank": 10,
        "queries": [
            '電気工事 株式会社 "info@" site:co.jp',
            '電気工事業者 "お問い合わせ" メール -求人',
            '設備工事 電気 有限会社 "contact@" -採用',
        ],
    },
    {
        "name": "リフォーム会社",
        "rank": 17,
        "queries": [
            'リフォーム会社 株式会社 "info@" site:co.jp',
            'リフォーム工事 "お問い合わせ" メール 株式会社 -求人',
            'リノベーション 有限会社 "contact@" -採用',
        ],
    },
    {
        "name": "建設設計事務所",
        "rank": 4,
        "queries": [
            '建築設計事務所 "info@" site:co.jp',
            '設計事務所 株式会社 "お問い合わせ" メール -求人',
            '一級建築士事務所 "contact@" -採用',
        ],
    },
    {
        "name": "訪問介護事業所",
        "rank": 3,
        "queries": [
            '訪問介護 株式会社 "info@" site:co.jp',
            '訪問介護事業所 "お問い合わせ" メール -求人',
            '訪問介護 有限会社 "contact@" -採用',
        ],
    },
    {
        "name": "社会保険労務士事務所",
        "rank": 1,
        "queries": [
            '社会保険労務士事務所 "info@" site:co.jp',
            '社労士事務所 "お問い合わせ" メール -求人',
            '社労士法人 "contact@" -採用',
        ],
    },
    {
        "name": "調剤薬局",
        "rank": 7,
        "queries": [
            '調剤薬局 株式会社 "info@" site:co.jp',
            '薬局 "お問い合わせ" メール -求人 -チェーン',
            '保険調剤 有限会社 "contact@"',
        ],
    },
    {
        "name": "土木・舗装工事業者",
        "rank": 20,
        "queries": [
            '土木工事 株式会社 "info@" site:co.jp',
            '舗装工事 "お問い合わせ" メール -求人',
            '土木建設 有限会社 "contact@" -採用',
        ],
    },
    {
        "name": "自動車整備業",
        "rank": 26,
        "queries": [
            '自動車整備 株式会社 "info@" site:co.jp',
            '車検 整備工場 "お問い合わせ" メール -求人',
            '自動車修理 有限会社 "contact@"',
        ],
    },
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
        print(f"    Brave エラー: {e}")
        return []


def _fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; BenchmarkBot/1.0)"})
        with urllib.request.urlopen(req, timeout=8) as r:
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
    return result[:3]


def benchmark_industry(industry: dict, pages_per_query: int = 8) -> dict:
    name = industry["name"]
    print(f"\n{'='*50}")
    print(f"  {name}（リスト{industry['rank']}位）")
    print(f"{'='*50}")

    total_results = 0
    fetched = 0
    email_found = 0
    good_domain = 0
    bad_domain = 0

    for query in industry["queries"]:
        print(f"  クエリ: {query[:55]}...")
        results = _brave_search(query, count=pages_per_query)
        total_results += len(results)
        time.sleep(1.2)

        for r in results:
            url = r.get("url", "")
            if not url:
                continue
            html = _fetch_html(url)
            if not html:
                time.sleep(0.3)
                continue
            fetched += 1
            emails = _extract_emails(html)
            if emails:
                email_found += 1
                for e in emails:
                    domain = e.split("@")[-1]
                    if any(domain.endswith(g) for g in GOOD_DOMAINS):
                        good_domain += 1
                    elif any(domain.endswith(b) for b in BAD_DOMAINS):
                        bad_domain += 1
                print(f"    OK {emails[0]}")
            time.sleep(0.8)

    email_rate = email_found / fetched * 100 if fetched > 0 else 0
    good_rate  = good_domain / email_found * 100 if email_found > 0 else 0

    print(f"\n  結果: Brave={total_results}件 / fetch={fetched}件 / メール={email_found}件")
    print(f"        メール取得率={email_rate:.1f}% / 良質ドメイン率={good_rate:.1f}%")

    return {
        "業種": name,
        "リスト順位": industry["rank"],
        "Brave結果数": total_results,
        "fetch数": fetched,
        "メール取得数": email_found,
        "メール取得率(%)": round(email_rate, 1),
        "良質ドメイン率(%)": round(good_rate, 1),
    }


def main():
    if not BRAVE_KEY:
        print("BRAVE_API_KEY が未設定です")
        return

    print("業種別リード取得率ベンチマーク開始")
    print(f"対象: {len(INDUSTRIES)}業種 × 3クエリ × 8件 = 最大{len(INDUSTRIES)*3*8}件フェッチ")
    print("※ Brave API の消費: 最大約200リクエスト\n")

    results = []
    for industry in INDUSTRIES:
        r = benchmark_industry(industry)
        results.append(r)
        time.sleep(2.0)

    # 結果表示
    print(f"\n\n{'='*70}")
    print("ベンチマーク結果（メール取得率順）")
    print(f"{'='*70}")
    results.sort(key=lambda x: x["メール取得率(%)"], reverse=True)

    print(f"{'業種':<20} {'順位':>4} {'fetch':>6} {'メール':>6} {'取得率':>8} {'良質':>8}")
    print("-" * 60)
    for r in results:
        print(f"{r['業種']:<20} {r['リスト順位']:>4}位 {r['fetch数']:>6} {r['メール取得数']:>6} {r['メール取得率(%)']:>7}% {r['良質ドメイン率(%)']:>7}%")

    # CSV保存
    out = Path(__file__).parent / "benchmark_results.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print(f"\n→ {out} に保存しました")


if __name__ == "__main__":
    main()
