"""楽天スクレイピング → Geminiキャプション生成 → products.csv追記（週1回）
ローカル実行専用: GitHub ActionsではPlaywright版を使用予定
"""
import os
import json
import time
import random
import re
from pathlib import Path
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from groq import Groq
from utils.product_picker import append_products

# .env 読み込み
_env_path = Path(__file__).parent.parent.parent.parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

JST = timezone(timedelta(hours=9))

CATEGORIES = [
    {"keyword": "コスメ 人気",        "name": "コスメ・美容",    "persona": "20〜30代女性"},
    {"keyword": "キッチン 便利",      "name": "キッチン用品",    "persona": "子育て世帯"},
    {"keyword": "収納 おしゃれ",      "name": "収納・インテリア", "persona": "一人暮らし/在宅ワーカー"},
    {"keyword": "ガジェット おすすめ", "name": "ガジェット・家電", "persona": "在宅ワーカー"},
]

GROQ_MODEL = "llama-3.3-70b-versatile"
TOP_N = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja-JP,ja;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _parse_review(text: str) -> tuple[float, int]:
    m = re.search(r"([\d.]+)\s*[\(（]([\d,]+)", text)
    if m:
        return float(m.group(1)), int(m.group(2).replace(",", ""))
    return 0.0, 0


def _fetch_ranking(category: dict) -> list[dict]:
    """楽天市場の検索結果をスクレイピングして商品リストを返す（ローカル用）"""
    url = "https://search.rakuten.co.jp/search/mall/" + requests.utils.quote(category["keyword"]) + "/"
    params = {"min": 500, "max": 8000, "s": 2}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  取得失敗({category['name']}): {e}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    seen_urls = set()
    items = []

    for a in soup.select("a[href*='item.rakuten.co.jp']"):
        name = a.get_text(strip=True)
        href = a.get("href", "")
        if not name or not href or href in seen_urls:
            continue
        seen_urls.add(href)

        parent = a.parent
        for _ in range(6):
            if parent is None:
                break
            txt = parent.get_text(" ", strip=True)
            if "円" in txt and len(txt) < 600:
                break
            parent = parent.parent
        if not parent:
            continue

        price_el = parent.select_one("[class*='price']") or parent.select_one("[class*='Price']")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = int("".join(filter(str.isdigit, price_text.split("円")[0])) or 0)
        if price == 0:
            continue

        review_el = (parent.select_one("[class*='review']") or
                     parent.select_one("[class*='rating']"))
        review_text = review_el.get_text(strip=True) if review_el else ""
        rating, review_count = _parse_review(review_text)

        items.append({
            "url": href, "name": name, "price": price,
            "rating": rating, "review_count": review_count, "in_stock": True,
        })
        if len(items) >= 30:
            break

    return items


def _score(item: dict) -> float:
    def normalize(val, max_val):
        return min(val / max_val, 1.0) if max_val > 0 else 0.0

    review_score = normalize(item["review_count"], 500)
    rating_score = normalize(item["rating"], 5.0)
    price = item["price"]
    if 500 <= price <= 5000:
        price_fit = 1.0
    elif price <= 8000:
        price_fit = 0.5
    else:
        price_fit = 0.1
    in_stock = 0.1 if item["in_stock"] else 0.0
    return round(review_score * 0.4 + rating_score * 0.3 + price_fit * 0.2 + in_stock, 3)


def _generate_captions(product: dict, category: dict, client: Groq) -> dict | None:
    prompt = f"""あなたは楽天ROOMのアフィリエイト投稿の専門家です。
以下の商品情報から、楽天ROOM投稿用のキャプションを生成してください。

商品情報:
{json.dumps(product, ensure_ascii=False)}
カテゴリ: {category['name']}
ターゲット: {category['persona']}

出力要件:
- 短文（80〜120字）× 丁寧/カジュアル/ママ向け の3パターン
- 中文（180〜250字）× 丁寧/カジュアル/ママ向け の3パターン
- 長文（350〜500字）× 丁寧/カジュアル/ママ向け の3パターン
- 各パターンの末尾にハッシュタグ（短文3個/中文5個/長文7個）
- 必ず #楽天ROOM を含める
- 絵文字は短文2個以内・中長文3個以内
- 景品表示法・薬機法準拠（断定・保証・医療効能の表現禁止）
- 価格・在庫は「{product['captured_at']}時点」と明記
- AIDA または PAS フレームワークを使用

以下のJSON形式のみで出力（他のテキスト不要）:
{{
  "copy": {{
    "短文": {{"丁寧": "...", "カジュアル": "...", "ママ向け": "..."}},
    "中文": {{"丁寧": "...", "カジュアル": "...", "ママ向け": "..."}},
    "長文": {{"丁寧": "...", "カジュアル": "...", "ママ向け": "..."}}
  }},
  "hashtags": ["#楽天ROOM", "..."]
}}"""

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            text = response.choices[0].message.content.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            print(f"    Groq失敗({attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(5)
    return None


def run():
    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    total_added = 0

    for category in CATEGORIES:
        print(f"\n--- {category['name']} ---")
        items = _fetch_ranking(category)
        print(f"  取得: {len(items)}件")
        if not items:
            continue

        # スコアリング・上位N件選抜
        for item in items:
            item["score"] = _score(item)
        items.sort(key=lambda x: x["score"], reverse=True)
        top = items[:TOP_N]

        new_rows = []
        for item in top:
            item["captured_at"] = now_str
            print(f"  [{item['score']:.2f}] {item['name'][:30]}")
            captions = _generate_captions(item, category, client)

            copy = captions.get("copy", {}) if captions else {}
            row = {
                "url": item["url"],
                "name": item["name"],
                "category": category["name"],
                "buyer_persona": category["persona"],
                "price": item["price"],
                "rating": item["rating"],
                "review_count": item["review_count"],
                "score": item["score"],
                "copy_short_polite":  copy.get("短文", {}).get("丁寧", ""),
                "copy_short_casual":  copy.get("短文", {}).get("カジュアル", ""),
                "copy_short_mom":     copy.get("短文", {}).get("ママ向け", ""),
                "copy_medium_polite": copy.get("中文", {}).get("丁寧", ""),
                "copy_medium_casual": copy.get("中文", {}).get("カジュアル", ""),
                "copy_medium_mom":    copy.get("中文", {}).get("ママ向け", ""),
                "copy_long_polite":   copy.get("長文", {}).get("丁寧", ""),
                "copy_long_casual":   copy.get("長文", {}).get("カジュアル", ""),
                "copy_long_mom":      copy.get("長文", {}).get("ママ向け", ""),
                "hashtags":      ",".join(captions.get("hashtags", [])) if captions else "",
                "evidence_url":  f"https://search.rakuten.co.jp/search/mall/{requests.utils.quote(category['keyword'])}/",
                "captured_at":   now_str,
                "posted":        "False",
                "posted_at":     "",
                "tone_used":     "",
            }
            new_rows.append(row)
            time.sleep(random.uniform(2, 4))

        append_products(new_rows)
        total_added += len(new_rows)
        print(f"  → {len(new_rows)}件追加")
        time.sleep(random.uniform(3, 6))

    print(f"\n[完了] 合計{total_added}件追加")


if __name__ == "__main__":
    run()
