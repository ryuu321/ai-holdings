"""
fetch_products.py — 楽天市場APIで商品を一括取得 → products.csvに追記
使い方: python fetch_products.py --count 8000
"""
import os
import re
import time
import random
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

from utils.product_picker import append_products

# .env 読み込み
_env = Path(__file__).parent.parent.parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

APP_ID     = os.environ["RAKUTEN_APP_ID"]
ACCESS_KEY = os.environ["RAKUTEN_ACCESS_KEY"]
AFF_ID     = os.environ.get("RAKUTEN_AFFILIATE_ID", "")
APP_URL    = "https://github.com/ryuu321/ai-holdings"
JST        = timezone(timedelta(hours=9))

API_URL  = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20260401"
HITS     = 30   # 1リクエストあたりの取得件数（最大30）
MIN_PRICE = 300
MAX_PRICE = 8000
MIN_REVIEWS = 5

SEARCH_TARGETS = [
    {"keyword": "コスメ 人気",           "category": "コスメ・美容",       "persona": "20〜30代女性"},
    {"keyword": "スキンケア おすすめ",    "category": "コスメ・美容",       "persona": "20〜30代女性"},
    {"keyword": "キッチン 便利グッズ",    "category": "キッチン用品",       "persona": "子育て世帯"},
    {"keyword": "収納 おしゃれ",          "category": "収納・インテリア",   "persona": "一人暮らし"},
    {"keyword": "ガジェット おすすめ",    "category": "ガジェット・家電",   "persona": "在宅ワーカー"},
    {"keyword": "ファッション レディース","category": "レディースファッション","persona": "20〜30代女性"},
    {"keyword": "雑貨 かわいい",          "category": "生活雑貨",           "persona": "20〜30代女性"},
    {"keyword": "ヘアケア 人気",          "category": "ヘアケア",           "persona": "20〜30代女性"},
    {"keyword": "ダイエット サプリ",      "category": "健康・美容",         "persona": "20〜40代女性"},
    {"keyword": "バッグ レディース",      "category": "バッグ・財布",       "persona": "20〜30代女性"},
]

HEADERS = {
    "Referer": APP_URL,
    "Origin":  APP_URL,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

HASHTAG_MAP = {
    "コスメ・美容":         ["#楽天ROOM", "#コスメ", "#美容", "#スキンケア", "#メイク"],
    "キッチン用品":         ["#楽天ROOM", "#キッチン", "#便利グッズ", "#料理", "#台所"],
    "収納・インテリア":     ["#楽天ROOM", "#収納", "#インテリア", "#おしゃれ", "#部屋"],
    "ガジェット・家電":     ["#楽天ROOM", "#ガジェット", "#家電", "#テック", "#便利"],
    "レディースファッション":["#楽天ROOM", "#ファッション", "#レディース", "#コーデ", "#おしゃれ"],
    "生活雑貨":             ["#楽天ROOM", "#雑貨", "#かわいい", "#生活", "#おしゃれ"],
    "ヘアケア":             ["#楽天ROOM", "#ヘアケア", "#髪", "#美髪", "#トリートメント"],
    "健康・美容":           ["#楽天ROOM", "#ダイエット", "#健康", "#美容", "#サプリ"],
    "バッグ・財布":         ["#楽天ROOM", "#バッグ", "#財布", "#レディース", "#ファッション"],
}


def _make_caption(item: dict, target: dict, style: str) -> str:
    name   = item["name"][:30]
    price  = item["price"]
    rating = item["rating"]
    tags   = " ".join(HASHTAG_MAP.get(target["category"], ["#楽天ROOM"])[:3])
    ts     = item["captured_at"]

    if style == "short_casual":
        return f"これ使ってる！{name}が{price:,}円で買えるよ✨ {tags}"
    elif style == "short_polite":
        return f"{name}、{price:,}円でご購入いただけます。{ts}時点、評価{rating}。 {tags}"
    elif style == "short_mom":
        return f"ママにおすすめ✨ {name}が{price:,}円！ {tags}"
    elif style == "medium_casual":
        return f"{name}をゲットしました💕 {price:,}円で{ts}時点で在庫あり。評価{rating}の人気商品です！ {tags}"
    elif style == "medium_polite":
        return f"{name}をご紹介します。{ts}時点で{price:,}円、評価{rating}の人気商品です。ぜひチェックしてみてください。 {tags}"
    elif style == "medium_mom":
        return f"子育て中のママに使ってほしい✨ {name}が{price:,}円！{ts}時点で在庫ありです。 {tags}"
    elif style == "long_polite":
        return f"{name}のご紹介です。{ts}時点で{price:,}円にてご購入いただけます。評価{rating}と高い評価を得ており、多くの方にご好評いただいております。この機会にぜひお試しください。 {' '.join(HASHTAG_MAP.get(target['category'], ['#楽天ROOM']))}"
    elif style == "long_casual":
        return f"めっちゃいい！{name}が{price:,}円💕 {ts}時点での情報だけど評価{rating}で超人気！気になってた人はチェックして✨ {' '.join(HASHTAG_MAP.get(target['category'], ['#楽天ROOM']))}"
    else:  # long_mom
        return f"ママたちの間で話題！{name}が{price:,}円で買えます💕 {ts}時点で在庫あり。評価{rating}の安心商品です。子育て中でも使いやすい一品をぜひ。 {' '.join(HASHTAG_MAP.get(target['category'], ['#楽天ROOM']))}"


def _fetch_page(keyword: str, page: int) -> list[dict]:
    for attempt in range(4):
        r = requests.get(API_URL, params={
            "applicationId": APP_ID,
            "accessKey":     ACCESS_KEY,
            "affiliateId":   AFF_ID,
            "keyword":       keyword,
            "hits":          HITS,
            "page":          page,
            "minPrice":      MIN_PRICE,
            "maxPrice":      MAX_PRICE,
            "sort":          "-reviewCount",
            "format":        "json",
        }, headers=HEADERS, timeout=15)
        if r.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f"    429 Rate limit → {wait}秒待機")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json().get("Items", [])
    return []


def run(total: int):
    per_target = max(1, total // len(SEARCH_TARGETS))
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    grand_total = 0

    for target in SEARCH_TARGETS:
        print(f"\n--- {target['category']} ({target['keyword']}) ---")
        collected = []
        page = 1
        seen_urls = set()

        while len(collected) < per_target:
            try:
                items = _fetch_page(target["keyword"], page)
            except Exception as e:
                print(f"  APIエラー(page={page}): {e}")
                break
            if not items:
                break

            for item_wrap in items:
                item = item_wrap["Item"]
                url   = item.get("affiliateUrl") or item.get("itemUrl", "")
                name  = item.get("itemName", "")
                price = item.get("itemPrice", 0)
                rating = float(item.get("reviewAverage", 0))
                reviews = int(item.get("reviewCount", 0))

                if not url or not name or price < MIN_PRICE or reviews < MIN_REVIEWS:
                    continue
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                score = round(
                    min(reviews / 500, 1.0) * 0.4 +
                    min(rating / 5.0, 1.0) * 0.3 +
                    (1.0 if MIN_PRICE <= price <= 5000 else 0.5) * 0.3,
                    3
                )
                product = {
                    "url": url, "name": name, "category": target["category"],
                    "buyer_persona": target["persona"],
                    "price": price, "rating": rating,
                    "review_count": reviews, "score": score,
                    "captured_at": now_str,
                }

                product["copy_short_polite"]  = _make_caption(product, target, "short_polite")
                product["copy_short_casual"]  = _make_caption(product, target, "short_casual")
                product["copy_short_mom"]     = _make_caption(product, target, "short_mom")
                product["copy_medium_polite"] = _make_caption(product, target, "medium_polite")
                product["copy_medium_casual"] = _make_caption(product, target, "medium_casual")
                product["copy_medium_mom"]    = _make_caption(product, target, "medium_mom")
                product["copy_long_polite"]   = _make_caption(product, target, "long_polite")
                product["copy_long_casual"]   = _make_caption(product, target, "long_casual")
                product["copy_long_mom"]      = _make_caption(product, target, "long_mom")
                product["hashtags"] = ",".join(HASHTAG_MAP.get(target["category"], ["#楽天ROOM"]))
                product["evidence_url"] = f"https://search.rakuten.co.jp/search/mall/{requests.utils.quote(target['keyword'])}/"
                product["posted"]    = "False"
                product["posted_at"] = ""
                product["tone_used"] = ""

                collected.append(product)
                if len(collected) >= per_target:
                    break

            page += 1
            if page > 100:
                break
            time.sleep(random.uniform(0.8, 1.2))

        if collected:
            append_products(collected)
            print(f"  → {len(collected)}件追加")
            grand_total += len(collected)

    print(f"\n[完了] 合計 {grand_total:,}件追加")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=500, help="取得する商品数")
    args = parser.parse_args()
    run(args.count)
