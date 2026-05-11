"""楽天ROOM自動投稿 - APIベース（Playwright fetch経由）"""
import asyncio
import json
import random
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.async_api import async_playwright

from utils.product_picker import get_pending, mark_posted, count_pending

JST = timezone(timedelta(hours=9))
AUTH_JSON = Path(__file__).parent / "auth.json"
TONE_INDEX_FILE = Path(__file__).parent / "data" / "tone_index.txt"
POSTS_PER_RUN = 70
DAILY_MAX = 280            # 1日の絶対上限（8000件/月目標 = 267/日）
LOW_STOCK_THRESHOLD = 2000  # 在庫がこれを下回ったら自動補充
DAILY_COUNT_FILE = Path(__file__).parent / "data" / "daily_count.json"

TONE_ROTATION = [
    "short_casual", "medium_polite", "short_mom",
    "medium_casual", "long_polite", "short_casual",
    "medium_mom", "long_casual", "short_polite",
]

TONE_COL_MAP = {
    "short_polite":   "copy_short_polite",
    "short_casual":   "copy_short_casual",
    "short_mom":      "copy_short_mom",
    "medium_polite":  "copy_medium_polite",
    "medium_casual":  "copy_medium_casual",
    "medium_mom":     "copy_medium_mom",
    "long_polite":    "copy_long_polite",
    "long_casual":    "copy_long_casual",
    "long_mom":       "copy_long_mom",
}


def get_current_tone() -> str:
    TONE_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    idx = int(TONE_INDEX_FILE.read_text().strip()) if TONE_INDEX_FILE.exists() else 0
    tone = TONE_ROTATION[idx % len(TONE_ROTATION)]
    TONE_INDEX_FILE.write_text(str(idx + 1))
    return tone


def get_today_count() -> int:
    today = datetime.now(JST).strftime("%Y-%m-%d")
    if not DAILY_COUNT_FILE.exists():
        return 0
    data = json.loads(DAILY_COUNT_FILE.read_text())
    return data.get(today, 0)


def add_today_count(n: int):
    today = datetime.now(JST).strftime("%Y-%m-%d")
    DAILY_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(DAILY_COUNT_FILE.read_text()) if DAILY_COUNT_FILE.exists() else {}
    data[today] = data.get(today, 0) + n
    # _total_override を累積更新
    data["_total_override"] = data.get("_total_override", 0) + n
    # 直近7日分 + _total_override を保持
    date_keys = sorted(k for k in data if k != "_total_override")[-7:]
    DAILY_COUNT_FILE.write_text(json.dumps({k: data[k] for k in date_keys} | {"_total_override": data["_total_override"]}))


def extract_item_key_from_url(url: str) -> str:
    """楽天商品URLからROOM用item_keyを生成: {shop}:{item_code}
    アフィリエイトURL(hb.afl.rakuten.co.jp)はpc=パラメータから実URLを取得する
    """
    # アフィリエイトURL → pc=パラメータから実URLを抽出
    if 'hb.afl.rakuten' in url:
        qs = parse_qs(urlparse(url).query)
        actual = qs.get('pc', [''])[0]
        if actual:
            url = actual

    m = re.search(r'item\.rakuten\.co\.jp/([^/]+)/([^/?#]+)', url)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return ''


async def post_product_api(page, csrf: str, item_key: str, item_name: str, caption: str) -> str:
    """APIで投稿。戻り値: 'ok' / 'duplicate' / 'not_found' / 'error'"""
    if len(item_key) > 32:
        print(f"    item_key長すぎ({len(item_key)}文字) → スキップ")
        return 'not_found'
    result = await page.evaluate(f"""
        (() => {{
            const params = new URLSearchParams();
            params.set('bu', 'ichiba');
            params.set('item_key', {json.dumps(item_key)});
            params.set('name', {json.dumps(item_name[:100])});
            params.set('content', {json.dumps(caption[:500])});
            params.set('pictures', '');
            return fetch('/api/collect?api_version=1&csrf_tkn={csrf}', {{
                method: 'POST',
                credentials: 'include',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json'
                }},
                body: params.toString()
            }}).then(r => r.json()).catch(e => ({{error: '' + e}}));
        }})()
    """)
    if isinstance(result, dict):
        if result.get('status') == 'success':
            return 'ok'
        msg_code = result.get('msg_code', '')
        if msg_code == 'R200':
            return 'duplicate'  # 既にROOMに投稿済み
        if msg_code in ('R119', 'R108'):
            return 'not_found'  # 商品がROOMに存在しない or item_key不正
    print(f"    投稿失敗: {result}")
    return 'error'


async def run():
    now = datetime.now(JST)
    print(f"\n{'='*55}")
    print(f"[rakuten-room] {now.strftime('%Y-%m-%d %H:%M JST')}")

    if not AUTH_JSON.exists():
        print("auth.json が見つかりません。セットアップが必要です。")
        return

    pending_count = count_pending()
    print(f"未投稿商品: {pending_count}件")
    if pending_count < LOW_STOCK_THRESHOLD:
        print(f"在庫 {pending_count}件 → 自動補充開始 (fetch_products.py --count 8000)")
        fetch_script = Path(__file__).parent / "fetch_products.py"
        subprocess.Popen([sys.executable, str(fetch_script), "--count", "8000"])
    if pending_count == 0:
        print("在庫補充中です。数分後に再実行されます。")
        return

    today_count = get_today_count()
    remaining_quota = DAILY_MAX - today_count
    print(f"本日投稿済み: {today_count}件 / 上限: {DAILY_MAX}件（残り: {remaining_quota}件）")
    if remaining_quota <= 0:
        print("本日の投稿上限に達しました。明日再開します。")
        return

    posts_this_run = min(POSTS_PER_RUN, remaining_quota)
    products = get_pending(posts_this_run)

    wait = random.randint(0, 60)
    print(f"待機: {wait}秒")
    await asyncio.sleep(wait)

    auth = json.loads(AUTH_JSON.read_text())
    cookies = [
        {
            'name': c['name'],
            'value': c['value'],
            'domain': c.get('domain', 'room.rakuten.co.jp'),
            'path': c.get('path', '/'),
        }
        for c in auth.get('cookies', [])
        if 'rakuten' in c.get('domain', '')
    ]

    success = 0
    fail = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
        )
        await context.add_cookies(cookies)
        page = await context.new_page()

        print("ROOM接続中...")
        await page.goto('https://room.rakuten.co.jp/items', wait_until='domcontentloaded', timeout=60000)
        await asyncio.sleep(3)

        page_content = await page.content()
        csrf_list = re.findall(
            r'csrf[_-]?t(?:kn|oken)["\']?\s*[:=]\s*["\']([a-f0-9]{30,})["\']',
            page_content, re.I
        )
        if not csrf_list:
            print("CSRFトークン取得失敗")
            await browser.close()
            return

        csrf = csrf_list[0]
        print(f"CSRF取得: {csrf[:16]}...")

        # ログイン状態確認
        current_url = page.url
        title = await page.title()
        print(f"ページURL: {current_url}")
        print(f"ページタイトル: {title[:60]}")

        for _, row in products.iterrows():
            tone = get_current_tone()
            col = TONE_COL_MAP.get(tone, "copy_short_casual")
            caption = row.get(col, "") or row.get("copy_short_casual", "")

            if not caption:
                for fallback_col in TONE_COL_MAP.values():
                    caption = row.get(fallback_col, "")
                    if caption:
                        break
            if not caption:
                caption = f"{row['name'][:30]}　楽天で人気の商品です"

            product_name = str(row.get('name', ''))
            product_url = str(row.get('url', ''))
            item_key = extract_item_key_from_url(product_url)
            print(f"\n  [{tone}] {product_name[:35]}")

            if not item_key:
                print(f"    item_key抽出失敗: {product_url[:60]}")
                fail += 1
                continue

            print(f"    item_key: {item_key}")
            result = await post_product_api(page, csrf, item_key, product_name[:100], caption)

            if result == 'ok':
                mark_posted(row["url"], tone)
                success += 1
                print(f"    投稿成功")
            elif result in ('duplicate', 'not_found'):
                # ROOMに既にある or 存在しない商品 → 再試行しないよう済み扱い
                mark_posted(row["url"], tone)
                fail += 1
                print(f"    スキップ({result}) → 投稿済みとしてマーク")
            else:
                fail += 1
                print(f"    投稿失敗")

            # 通常30〜90秒待機、10回に1回は2〜4分の長めブレーク（人間らしく）
            if (success + fail) % 10 == 0:
                pause = random.uniform(120, 240)
                print(f"    [ブレーク] {pause:.0f}秒")
                await asyncio.sleep(pause)
            else:
                await asyncio.sleep(random.uniform(30, 90))

        await browser.close()

    add_today_count(success)
    print(f"\n{'='*55}")
    print(f"[完了] {success}/{len(products)}件 投稿成功")


if __name__ == "__main__":
    asyncio.run(run())
