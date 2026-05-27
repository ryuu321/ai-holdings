"""
Geminiを使ったAI会社名抽出ユーティリティ

使い方:
  from shared.gtm.outreach.extract_company import extract_company_name_ai
  company = extract_company_name_ai(html, url)

  # 単体テスト
  python extract_company.py --url https://example.co.jp
"""
import json
import os
import re
import sys
import urllib.request
from urllib.parse import urlparse

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")

# 法人格キーワード（会社名らしさの判定）
_COMPANY_KEYWORDS = [
    "株式会社", "有限会社", "合同会社", "一般社団法人", "公益社団法人",
    "社会保険労務士法人", "社労士法人", "社会保険労務士事務所", "社労士事務所",
    "行政書士法人", "行政書士事務所", "司法書士法人", "司法書士事務所",
    "税理士法人", "税理士事務所", "弁護士法人", "弁護士事務所",
    "医療法人", "学校法人", "社会福祉法人", "宗教法人",
    "事務所", "法人", "工務店", "設計事務所", "建設", "不動産",
]

# ブログ・まとめサイト判定シグナル
_BLOG_SIGNALS = [
    "コツ", "方法", "選び方", "探し方", "ランキング", "比較", "一覧",
    "とは", "について", "の仕方", "ガイド", "まとめ", "おすすめ",
    "名簿", "営業リスト", "お問い合わせ方法",
]


def extract_company_name_ai(html: str, url: str = "") -> str:
    """
    HTMLとURLからGeminiで会社名を抽出。失敗時はドメイン名を返す。

    優先順位:
    1. HTML解析（og:site_name / titleタグ） — 高速・API不要
    2. Gemini Flash Lite — SEOタイトル対応
    3. ドメイン名フォールバック — 絶対に空文字を返さない

    Args:
        html: スクレイピングしたHTML文字列
        url:  対象URL（フォールバック用）

    Returns:
        会社名文字列（空文字なし・必ず何か返す）
    """
    # ステップ1: HTML解析（高速パス）
    name = _extract_from_html(html)
    if name:
        return name

    # ステップ2: Gemini API で抽出
    if GEMINI_KEY and html:
        name = _extract_via_gemini(html, url)
        if name and name != "UNKNOWN":
            return name

    # ステップ3: ドメイン名フォールバック（絶対に空にしない）
    fallback = _domain_fallback(url)
    return fallback if fallback else "不明企業"


def _extract_from_html(html: str) -> str:
    """既存のHTML解析ロジック（og:site_name / titleタグ）"""
    OG_RE = re.compile(
        r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']{2,40})["\']'
        r'|<meta[^>]+content=["\']([^"\']{2,40})["\'][^>]+property=["\']og:site_name["\']',
        re.IGNORECASE,
    )
    TITLE_RE = re.compile(r"<title[^>]*>([^<]+)</title>", re.IGNORECASE)

    # og:site_name チェック
    m = OG_RE.search(html)
    if m:
        name = (m.group(1) or m.group(2) or "").strip()
        if name and any(kw in name for kw in _COMPANY_KEYWORDS) and len(name) <= 40:
            return name
        if name and not any(sig in name for sig in _BLOG_SIGNALS) and 2 <= len(name) <= 30:
            return name

    # titleタグから区切り文字で分割して抽出
    t = TITLE_RE.search(html)
    if t:
        title = t.group(1).strip()
        for sep in ["｜", "|", "–", "—", " - ", "　"]:
            if sep not in title:
                continue
            parts = title.split(sep)
            for part in parts:
                part = part.strip()
                # 法人格キーワードを含む部分
                if any(kw in part for kw in _COMPANY_KEYWORDS) and 2 <= len(part) <= 40:
                    return part

    return ""


def _extract_via_gemini(html: str, url: str = "") -> str:
    """Gemini Flash Liteで会社名を抽出"""
    # HTMLタグを除去してプレーンテキスト化（先頭1500文字）
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()[:1500]

    prompt = (
        f"以下はウェブサイト（{url}）のテキストです。\n"
        "このウェブサイトを運営している会社・事務所・法人の正式名称を1つだけ答えてください。\n"
        "「株式会社○○」「○○社会保険労務士事務所」「○○法人」のような形式で。\n"
        "わからない場合は「UNKNOWN」とだけ答えてください。余計な説明は不要です。\n\n"
        f"テキスト:\n{text}"
    )

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 30, "temperature": 0},
    }).encode()

    api_url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash-lite:generateContent?key={GEMINI_KEY}"
    )
    try:
        req = urllib.request.Request(
            api_url, data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        name = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        name = name.replace("「", "").replace("」", "").replace("*", "").strip()
        if 2 <= len(name) <= 40 and name != "UNKNOWN":
            return name
    except Exception as e:
        # 静かに失敗してフォールバックへ
        print(f"  [extract_company] Gemini API エラー: {e}", file=sys.stderr)

    return "UNKNOWN"


def _domain_fallback(url: str) -> str:
    """URLのドメインから会社名を生成（最終フォールバック）"""
    if not url:
        return ""
    try:
        domain = urlparse(url).netloc.lower()
        domain = re.sub(r"^www\.", "", domain)
        # .co.jp / .com / .jp / .net / .org などを除去
        domain = re.sub(r"\.(co\.jp|or\.jp|ne\.jp|gr\.jp|com|jp|net|org|info)$", "", domain)
        # ハイフン・ドット・アンダースコアをそのまま保持（可読性のため）
        if len(domain) >= 2:
            return domain
    except Exception:
        pass
    return ""


# ── 単体テスト用エントリポイント ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    # .envを読む
    try:
        from pathlib import Path
        env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                k, _, v = line.partition("=")
                if v and k.strip() and k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip()
        GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="会社名抽出ユーティリティ テスト")
    parser.add_argument("--url", required=True, help="テスト対象URL")
    parser.add_argument("--html-file", help="HTMLファイルパス（省略時はURLからフェッチ）")
    args = parser.parse_args()

    if args.html_file:
        from pathlib import Path
        html = Path(args.html_file).read_text(encoding="utf-8", errors="ignore")
    else:
        print(f"フェッチ中: {args.url}")
        try:
            req = urllib.request.Request(
                args.url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; TextSeriesBot/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
                enc = r.headers.get_content_charset("utf-8")
                html = raw.decode(enc, errors="ignore")
        except Exception as e:
            print(f"フェッチ失敗: {e}")
            html = ""

    print(f"\n--- HTML解析のみ ---")
    print(repr(_extract_from_html(html)))

    print(f"\n--- Gemini抽出 ---")
    print(repr(_extract_via_gemini(html, args.url)))

    print(f"\n--- フォールバック ---")
    print(repr(_domain_fallback(args.url)))

    print(f"\n--- 総合結果 ---")
    result = extract_company_name_ai(html, args.url)
    print(f"会社名: {result}")
