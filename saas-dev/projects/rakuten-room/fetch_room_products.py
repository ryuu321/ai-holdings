"""
fetch_room_products.py — ROOMページを直接スクレイプして投稿可能な商品を収集
ROOMに掲載されている商品 = ROOMのDBに確実に存在する = R119にならない

使い方: python fetch_room_products.py --count 300
"""
import asyncio
import json
import re
import random
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, unquote

from playwright.async_api import async_playwright
from utils.product_picker import append_products

AUTH_JSON = Path(__file__).parent / "auth.json"
JST = timezone(timedelta(hours=9))

# スクレイプ対象ページ（フィード + カテゴリ + ランキング）
ROOM_FEED_PAGES = [
    "https://room.rakuten.co.jp/items",
    "https://room.rakuten.co.jp/items?page=2",
    "https://room.rakuten.co.jp/items?page=3",
    "https://room.rakuten.co.jp/items?page=4",
    "https://room.rakuten.co.jp/items?page=5",
    "https://room.rakuten.co.jp/ranking",
    "https://room.rakuten.co.jp/ranking?page=2",
    "https://room.rakuten.co.jp/ranking?page=3",
    "https://room.rakuten.co.jp/items?category=ladies_fashion",
    "https://room.rakuten.co.jp/items?category=cosmetics",
    "https://room.rakuten.co.jp/items?category=interior",
    "https://room.rakuten.co.jp/items?category=kitchen",
]

HASHTAG_MAP = {
    "コスメ・美容":         "#楽天ROOM #コスメ #美容 #スキンケア",
    "ヘアケア":             "#楽天ROOM #ヘアケア #美髪 #トリートメント",
    "生活雑貨":             "#楽天ROOM #雑貨 #かわいい #おしゃれ",
    "収納・インテリア":     "#楽天ROOM #収納 #インテリア #部屋",
    "キッチン用品":         "#楽天ROOM #キッチン #便利グッズ #料理",
    "レディースファッション":"#楽天ROOM #ファッション #コーデ #レディース",
    "健康・美容":           "#楽天ROOM #健康 #美容 #ダイエット",
    "バッグ・財布":         "#楽天ROOM #バッグ #財布 #レディース",
}


def _extract_ichiba_url(url: str) -> str:
    """アフィリエイトURLを実URLに変換"""
    url = str(url)
    if "hb.afl.rakuten" in url:
        qs = parse_qs(urlparse(url).query)
        actual = qs.get("pc", [""])[0]
        if actual:
            url = unquote(actual)
    return url


def _extract_item_key(url: str) -> str:
    """楽天商品URLからitem_keyを生成"""
    url = _extract_ichiba_url(url)
    m = re.search(r"item\.rakuten\.co\.jp/([^/]+)/([^/?#]+)", url)
    if not m:
        return ""
    key = f"{m.group(1)}:{m.group(2)}"
    return key if len(key) <= 32 else ""


def _guess_category(name: str, url: str) -> str:
    name_lower = (name + url).lower()
    if any(k in name_lower for k in ["コスメ", "スキンケア", "メイク", "美容液", "化粧"]):
        return "コスメ・美容"
    if any(k in name_lower for k in ["シャンプー", "ヘア", "トリートメント", "hair"]):
        return "ヘアケア"
    if any(k in name_lower for k in ["ワンピース", "スカート", "ブラウス", "ジャケット", "fashion"]):
        return "レディースファッション"
    if any(k in name_lower for k in ["バッグ", "財布", "ポーチ", "bag"]):
        return "バッグ・財布"
    if any(k in name_lower for k in ["収納", "棚", "インテリア", "tower", "living"]):
        return "収納・インテリア"
    if any(k in name_lower for k in ["キッチン", "鍋", "フライパン", "調理", "kitchen"]):
        return "キッチン用品"
    if any(k in name_lower for k in ["サプリ", "ダイエット", "健康", "プロテイン"]):
        return "健康・美容"
    return "生活雑貨"


def _make_captions(name: str, price: int, category: str) -> dict:
    tags = HASHTAG_MAP.get(category, "#楽天ROOM #おすすめ #楽天")
    n = name[:30] if name else "おすすめ商品"
    p = f"{price:,}" if price else "お手頃"
    return {
        "copy_short_polite":  f"{n}をご紹介。{p}円でお求めいただけます。 {tags}",
        "copy_short_casual":  f"これ超おすすめ！{n}が{p}円✨ {tags}",
        "copy_short_mom":     f"ママにもおすすめ✨ {n}が{p}円！ {tags}",
        "copy_medium_polite": f"ROOMで見つけた{n}。{p}円でとてもお得です。ぜひチェックしてみてください。 {tags}",
        "copy_medium_casual": f"{n}をゲット！{p}円で大満足💕 みんなにシェアしたくて投稿しました✨ {tags}",
        "copy_medium_mom":    f"子育て中のママにも使ってほしい✨ {n}が{p}円！ {tags}",
        "copy_long_polite":   f"今回ご紹介するのは{n}です。{p}円でご購入いただけます。ROOMで話題の一品をぜひお試しください。 {tags}",
        "copy_long_casual":   f"めっちゃいい！{n}が{p}円💕 ROOMで見かけて即チェック。気になってた人はこの機会にどうぞ✨ {tags}",
        "copy_long_mom":      f"ママたちの間で話題！{n}が{p}円で買えます💕 子育て中でも使いやすい一品をぜひ。 {tags}",
    }


async def scrape(total: int):
    now_str = datetime.now(JST).strftime("%Y-%m-%d %H:%M")

    # auth.json 読み込み
    cookies, origins = [], []
    if AUTH_JSON.exists():
        auth = json.loads(AUTH_JSON.read_text())
        cookies = [
            {"name": c["name"], "value": c["value"],
             "domain": c.get("domain", "room.rakuten.co.jp"),
             "path": c.get("path", "/")}
            for c in auth.get("cookies", []) if "rakuten" in c.get("domain", "")
        ]
        origins = auth.get("origins", [])

    found_keys: set[str] = set()
    products: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        )
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        # localStorage復元
        for origin in origins:
            url = origin.get("origin", "")
            ls = origin.get("localStorage", [])
            if url and ls:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    for item in ls:
                        await page.evaluate(
                            f"localStorage.setItem({json.dumps(item['name'])}, {json.dumps(item['value'])})"
                        )
                except Exception:
                    pass

        # ネットワーク応答から商品データを収集
        api_items: list[dict] = []

        async def on_response(response):
            if "room.rakuten.co.jp" not in response.url:
                return
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct:
                return
            try:
                data = await response.json()
                _extract_from_json(data, api_items)
            except Exception:
                pass

        page.on("response", on_response)

        for feed_url in ROOM_FEED_PAGES:
            if len(products) >= total:
                break
            print(f"  取得中: {feed_url}")
            try:
                await page.goto(feed_url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3)

                # スクロールして追加アイテムをロード
                for _ in range(15):
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await asyncio.sleep(0.5)

                # DOM から楽天商品リンクを全取得
                hrefs: list[str] = await page.evaluate("""
                    () => {
                        const links = new Set();
                        document.querySelectorAll('a').forEach(a => {
                            const h = a.href || '';
                            if (h.includes('item.rakuten.co.jp') || h.includes('hb.afl.rakuten')) {
                                links.add(h);
                            }
                        });
                        return [...links];
                    }
                """)

                # __NEXT_DATA__ JSON からも抽出
                next_data_raw = await page.evaluate("""
                    () => {
                        const el = document.getElementById('__NEXT_DATA__');
                        return el ? el.textContent : '';
                    }
                """)
                if next_data_raw:
                    try:
                        _extract_from_json(json.loads(next_data_raw), api_items)
                    except Exception:
                        pass

                # ページ本文からアフィリエイトURL/Ichiba URLを正規表現で抽出
                content = await page.content()
                # アフィリエイトURL内の pc= から実URL
                for encoded in re.findall(r'pc=(https?[^"\'&\s]+item\.rakuten[^"\'&\s]+)', content):
                    hrefs.append(unquote(encoded))
                # 直接埋め込まれた Ichiba URL
                for url in re.findall(r'https?://item\.rakuten\.co\.jp/[^/"\'\\s]+/[^/"\'\\s]+', content):
                    hrefs.append(url)

                # api_items から URL を追加
                for ai in api_items:
                    u = ai.get("url", "")
                    if u:
                        hrefs.append(u)

                # item_key を抽出して products に追加
                for href in hrefs:
                    if len(products) >= total:
                        break
                    item_key = _extract_item_key(href)
                    if not item_key or item_key in found_keys:
                        continue
                    found_keys.add(item_key)

                    # API から取得できた詳細情報を検索
                    ichiba_url = _extract_ichiba_url(href)
                    matched = next(
                        (ai for ai in api_items
                         if _extract_item_key(ai.get("url", "")) == item_key),
                        {}
                    )
                    name = matched.get("name") or matched.get("itemName") or item_key.split(":")[0] + "の商品"
                    price = int(matched.get("price") or matched.get("itemPrice") or 1500)
                    category = _guess_category(name, ichiba_url)

                    product = {
                        "url": ichiba_url,
                        "name": name[:200],
                        "category": category,
                        "buyer_persona": "20〜30代女性",
                        "price": price,
                        "rating": float(matched.get("rating") or matched.get("reviewAverage") or 0),
                        "review_count": int(matched.get("review_count") or matched.get("reviewCount") or 0),
                        "score": 9.99,  # ROOMに掲載済み確定 → 最優先（Ichiba最高1.0超え）
                        "hashtags": HASHTAG_MAP.get(category, "#楽天ROOM #おすすめ"),
                        "evidence_url": feed_url,
                        "captured_at": now_str,
                        "posted": "False",
                        "posted_at": "",
                        "tone_used": "",
                        **_make_captions(name, price, category),
                    }
                    products.append(product)
                    print(f"    ✓ {item_key} [{category}]")

            except Exception as e:
                print(f"  エラー({feed_url}): {e}")

            await asyncio.sleep(random.uniform(2, 4))

        await browser.close()

    print(f"\n取得完了: {len(products)}件")
    if products:
        append_products(products)
        print("products.csv に追記しました")
    return len(products)


def _extract_from_json(data, out: list):
    """JSON再帰探索: 楽天商品URLまたはshopCode+itemCodeを含むオブジェクトを収集"""
    if isinstance(data, dict):
        url = (data.get("itemUrl") or data.get("url") or
               data.get("item_url") or data.get("affiliateUrl") or
               data.get("productUrl") or data.get("linkUrl") or "")
        found = "item.rakuten.co.jp" in str(url) or "hb.afl.rakuten" in str(url)

        # shopCode+itemCode で合成URLを試みる
        if not found:
            shop = data.get("shopCode") or data.get("shop_code") or data.get("shopId") or ""
            item = (data.get("itemCode") or data.get("item_code") or
                    data.get("itemId") or data.get("item_id") or "")
            if shop and item:
                url = f"https://item.rakuten.co.jp/{shop}/{item}/"
                found = True

        if found:
            out.append({
                "url": url,
                "name": (data.get("name") or data.get("itemName") or
                         data.get("title") or data.get("itemTitle") or ""),
                "price": data.get("price") or data.get("itemPrice") or data.get("minPrice") or 0,
                "rating": data.get("rating") or data.get("reviewAverage") or 0,
                "review_count": data.get("reviewCount") or data.get("review_count") or 0,
            })
        for v in data.values():
            if isinstance(v, (dict, list)):
                _extract_from_json(v, out)
    elif isinstance(data, list):
        for item in data:
            _extract_from_json(item, out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=300)
    args = parser.parse_args()
    asyncio.run(scrape(args.count))


if __name__ == "__main__":
    main()
