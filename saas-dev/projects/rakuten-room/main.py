"""楽天ROOM自動投稿 - APIベース（Playwright fetch経由）"""
import asyncio
import json
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.async_api import async_playwright

from utils.product_picker import get_pending, mark_posted, count_pending

RAKUTEN_ID = os.environ.get("RAKUTEN_ID", "")
RAKUTEN_PASSWORD = os.environ.get("RAKUTEN_PASSWORD", "")

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


async def do_login(page, context=None) -> bool:
    """楽天アカウントSSO経由でRoom用セッションを取得する。"""
    if not RAKUTEN_ID or not RAKUTEN_PASSWORD:
        print("RAKUTEN_ID/RAKUTEN_PASSWORD未設定 → 自動ログインスキップ")
        return False
    print("楽天ログイン実行中...")
    try:
        # ROOMに遷移してログイン状態を確認（クッキーはクリアしない）
        await page.goto("https://room.rakuten.co.jp/items", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)

        # ページ内のlogin_status確認（楽天ROOMはURL変化なしに未ログイン状態を返す場合がある）
        current = page.url
        page_content_check = await page.content()
        already_logged_in = (
            '"login_status":"on"' in page_content_check
            or '"loginStatus":"on"' in page_content_check
        )
        if "login" not in current and "account.rakuten" not in current and already_logged_in:
            print("  既にログイン済み（login_status確認済み）")
            return True

        # 古いクッキーを消してからログインページへ（干渉防止）
        if context:
            await context.clear_cookies()

        login_url = "https://grp01.id.rakuten.co.jp/rms/nid/login?service_id=room&return_url=https://room.rakuten.co.jp/items"
        await page.goto(login_url, wait_until="networkidle", timeout=45000)
        await asyncio.sleep(2)
        print(f"  ログインページ: {page.url}")

        # ユーザーID入力欄が現れるまで最大20秒待つ
        try:
            await page.wait_for_selector('input[name="u"]', timeout=20000)
        except Exception:
            # フォールバック: email/text 入力を試す
            found = False
            for sel in ['input[type="email"]', 'input[type="text"]', 'input[name="login_id"]']:
                try:
                    await page.wait_for_selector(sel, timeout=3000)
                    found = True
                    break
                except Exception:
                    pass
            if not found:
                title = await page.title()
                print(f"  ログインID入力欄が見つかりません（URL: {page.url} / タイトル: {title}）")
                print("  → Rakutenがこの環境からのログインをブロックしています。RAKUTEN_AUTH_JSONシークレットをローカルで更新してください。")
                return False

        # IDを入力（最初に見つかった入力欄に）
        for id_sel in ['input[name="u"]', 'input[type="email"]', 'input[type="text"]', 'input[name="login_id"]']:
            el = await page.query_selector(id_sel)
            if el and await el.is_visible():
                await el.fill(RAKUTEN_ID)
                break
        await asyncio.sleep(0.5)

        # パスワード入力
        try:
            await page.wait_for_selector('input[name="p"], input[type="password"]', timeout=5000)
        except Exception:
            print("  パスワード欄が見つかりません")
            return False
        for pw_sel in ['input[name="p"]', 'input[type="password"]']:
            el = await page.query_selector(pw_sel)
            if el and await el.is_visible():
                await el.fill(RAKUTEN_PASSWORD)
                break
        await asyncio.sleep(0.5)

        # ログインボタンをクリック
        for submit_sel in ['input[type="submit"]', 'button[type="submit"]']:
            try:
                sub_el = await page.query_selector(submit_sel)
                if sub_el and await sub_el.is_visible():
                    await sub_el.click()
                    break
            except Exception:
                pass

        # ログイン完了待ち（room.rakuten.co.jpへのリダイレクト）
        await page.wait_for_url(re.compile(r'room\.rakuten\.co\.jp'), timeout=30000)
        await asyncio.sleep(2)
        print(f"  ログイン後URL: {page.url}")
        print("楽天ログイン成功")
        return True
    except Exception as e:
        print(f"楽天ログインエラー: {e}")
        return False


async def save_cookies(context, path: Path):
    """現在のブラウザコンテキストのクッキーをauth.jsonに保存する。"""
    try:
        cookies = await context.cookies()
        path.write_text(json.dumps({"cookies": cookies}, ensure_ascii=False, indent=2))
        print(f"auth.json更新完了 ({len(cookies)}件)")
    except Exception as e:
        print(f"auth.json保存エラー: {e}")


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
        msg = str(result.get('msg', '') or result.get('message', ''))
        if msg_code == 'R200':
            return 'duplicate'
        if msg_code in ('R119', 'R108'):
            return 'not_found'
        if '上限' in msg or msg_code in ('R001', 'R900', 'R999'):
            print(f"    ご利用上限 [code={msg_code}] msg={msg[:80]} → 本日の投稿を終了")
            return 'limit'
    print(f"    投稿失敗: {json.dumps(result, ensure_ascii=False)[:200]}")
    return 'error'


async def run():
    now = datetime.now(JST)
    print(f"\n{'='*55}")
    print(f"[rakuten-room] {now.strftime('%Y-%m-%d %H:%M JST')}")

    if not AUTH_JSON.exists():
        if not RAKUTEN_ID or not RAKUTEN_PASSWORD:
            print("auth.json が見つかりません。RAKUTEN_ID/RAKUTEN_PASSWORD も未設定のため終了。")
            return
        print("auth.json が見つかりません → ログインで取得します")

    pending_count = count_pending()
    print(f"未投稿商品: {pending_count}件")
    if pending_count < LOW_STOCK_THRESHOLD:
        print(f"在庫 {pending_count}件 → ROOM直接スクレイプで補充開始")
        fetch_script = Path(__file__).parent / "fetch_room_products.py"
        subprocess.Popen([sys.executable, str(fetch_script), "--count", "500"])
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
    products = get_pending(posts_this_run, min_score=9.0)  # ROOM確認済み優先
    print(f"投稿候補: {len(products)}件（ROOM確認済み優先）")

    wait = random.randint(0, 60)
    print(f"待機: {wait}秒")
    await asyncio.sleep(wait)

    cookies = []
    origins = []
    if AUTH_JSON.exists():
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
        origins = auth.get('origins', [])
        print(f"auth.jsonからクッキー読込: {len(cookies)}件 / origin: {len(origins)}件")

    success = 0
    fail = 0
    login_attempted = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
        )
        if cookies:
            await context.add_cookies(cookies)
        page = await context.new_page()

        # localStorageを復元（セッション状態の維持に必要）
        if origins:
            for origin in origins:
                url = origin.get('origin', '')
                ls = origin.get('localStorage', [])
                if url and ls:
                    try:
                        await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                        for item in ls:
                            await page.evaluate(
                                f"localStorage.setItem({json.dumps(item['name'])}, {json.dumps(item['value'])})"
                            )
                    except Exception:
                        pass

        print("ROOM接続中...")
        await page.goto('https://room.rakuten.co.jp/items', wait_until='domcontentloaded', timeout=60000)
        await asyncio.sleep(3)

        current_url = page.url
        title = await page.title()
        page_html = await page.content()
        login_status = "on" if ('"login_status":"on"' in page_html or '"loginStatus":"on"' in page_html) else "off"
        print(f"ページURL: {current_url}")
        print(f"ページタイトル: {title[:60]}")
        print(f"ログイン状態: {login_status}")

        # セッション切れ検出: ログインページにリダイレクトされた場合
        if "login" in current_url or "account.rakuten.com" in current_url:
            print("セッション切れ検出 → 自動ログイン")
            ok = await do_login(page, context)
            login_attempted = True
            if ok:
                await save_cookies(context, AUTH_JSON)
            else:
                print("ログイン失敗 → 終了")
                await browser.close()
                return
            current_url = page.url
            title = await page.title()
            print(f"ログイン後URL: {current_url}")

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

            # 最初の403でセッション再取得を1回だけ試みる
            if result == 'error' and not login_attempted and (success + fail) == 0:
                print("    初回403 → セッション再取得を試みます")
                ok = await do_login(page, context)
                login_attempted = True
                if ok:
                    await save_cookies(context, AUTH_JSON)
                    # 新しいCSRFを取得
                    await page.goto('https://room.rakuten.co.jp/items', wait_until='domcontentloaded', timeout=30000)
                    await asyncio.sleep(3)
                    new_content = await page.content()
                    new_csrf_list = re.findall(
                        r'csrf[_-]?t(?:kn|oken)["\']?\s*[:=]\s*["\']([a-f0-9]{30,})["\']',
                        new_content, re.I
                    )
                    if new_csrf_list:
                        csrf = new_csrf_list[0]
                        print(f"    新CSRF取得: {csrf[:16]}...")
                        result = await post_product_api(page, csrf, item_key, product_name[:100], caption)

            if result == 'ok':
                mark_posted(row["url"], tone)
                success += 1
                print(f"    投稿成功")
            elif result == 'limit':
                # 利用上限 → ループ即終了
                break
            elif result in ('duplicate', 'not_found'):
                mark_posted(row["url"], tone)
                fail += 1
                print(f"    スキップ({result}) → 投稿済みとしてマーク")
            else:
                fail += 1
                print(f"    投稿失敗")

            # not_foundは短く、それ以外は1分前後
            if result == 'not_found':
                await asyncio.sleep(random.uniform(3, 5))
            else:
                await asyncio.sleep(random.uniform(50, 70))

        await browser.close()

    add_today_count(success)
    print(f"\n{'='*55}")
    print(f"[完了] {success}/{len(products)}件 投稿成功")


if __name__ == "__main__":
    asyncio.run(run())
