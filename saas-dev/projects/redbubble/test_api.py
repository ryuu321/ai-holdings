"""
Redbubble直接APIアップロードテスト
- manage_works（Cloudflare非保護）からCSRFトークン取得
- APIで直接ファイルアップロード
"""
import asyncio
import json
import re
import urllib.request
import urllib.parse
from pathlib import Path
from playwright.async_api import async_playwright

AUTH_FILE  = Path(__file__).parent / "data" / "rb_auth.json"
DESIGN_DIR = Path(__file__).parent / "data" / "designs"
RB_BASE    = "https://www.redbubble.com"


def get_cookies_header(auth_file: Path) -> str:
    """rb_auth.jsonのクッキーをCookieヘッダー文字列に変換"""
    if not auth_file.exists():
        return ""
    cookies = json.loads(auth_file.read_text(encoding="utf-8")).get("cookies", [])
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


async def get_csrf_and_upload_url():
    """Playwrightで manage_works からCSRF・アップロードURL取得"""
    storage = json.loads(AUTH_FILE.read_text(encoding="utf-8")) if AUTH_FILE.exists() else None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(storage_state=storage)
        page    = await context.new_page()

        await page.goto(f"{RB_BASE}/portfolio/manage_works",
                        wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(3)
        print(f"  manage_works URL: {page.url}")

        html = await page.content()

        # CSRFトークンを探す
        csrf = None
        for pattern in [
            r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']',
            r'"csrfToken"\s*:\s*"([^"]+)"',
            r'"authenticity_token"\s*:\s*"([^"]+)"',
            r'<input[^>]+name=["\']authenticity_token["\'][^>]+value=["\']([^"\']+)["\']',
        ]:
            m = re.search(pattern, html)
            if m:
                csrf = m.group(1)
                print(f"  CSRF token found: {csrf[:20]}...")
                break

        if not csrf:
            print("  CSRF token NOT found")
            print(f"  HTML excerpt: {html[500:1000]}")

        await browser.close()
        return csrf


async def try_direct_upload(image_path: Path, csrf: str):
    """直接APIでアップロード試行"""
    import mimetypes
    import uuid

    cookie_header = get_cookies_header(AUTH_FILE)

    # Redbubble のアップロードエンドポイント候補
    endpoints = [
        f"{RB_BASE}/portfolio/images",
        f"{RB_BASE}/api/v1/portfolio/images",
    ]

    boundary = uuid.uuid4().hex
    img_data  = image_path.read_bytes()
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/png"

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="authenticity_token"\r\n\r\n'
        f"{csrf}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="image[source_file]"; filename="{image_path.name}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode() + img_data + f"\r\n--{boundary}--\r\n".encode()

    headers = {
        "Cookie":       cookie_header,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "X-CSRF-Token": csrf,
        "User-Agent":   "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer":      f"{RB_BASE}/portfolio/images/new",
        "Origin":       RB_BASE,
        "Accept":       "application/json, text/javascript, */*",
    }

    for url in endpoints:
        print(f"\n  POST {url}")
        try:
            req  = urllib.request.Request(url, data=body, headers=headers, method="POST")
            resp = urllib.request.urlopen(req, timeout=30)
            text = resp.read().decode(errors="replace")
            print(f"  Status: {resp.status}")
            print(f"  Response: {text[:300]}")
            return True
        except urllib.error.HTTPError as e:
            body_text = e.read().decode(errors="replace")
            print(f"  HTTP {e.code}: {body_text[:200]}")
        except Exception as e:
            print(f"  Error: {e}")

    return False


async def main():
    print("=== Redbubble API直接アップロードテスト ===")
    csrf = await get_csrf_and_upload_url()

    if not csrf:
        print("\nCSRFトークン取得不可 → API呼び出し不可能")
        return

    # 最初のデザインを使ってテスト
    designs = sorted(DESIGN_DIR.glob("*.png"))
    if not designs:
        print("デザイン画像がありません")
        return

    image = designs[0]
    print(f"\n  テスト画像: {image.name}")
    await try_direct_upload(image, csrf)


asyncio.run(main())
