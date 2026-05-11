"""
CDP経由でユーザーの実Chrome に接続してアップロードページへアクセス
"""
import asyncio
import subprocess
import os
import time
import socket
from pathlib import Path
from playwright.async_api import async_playwright

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]
CHROME = next((p for p in CHROME_PATHS if Path(p).exists()), None)
USER_DATA = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
DEBUG_PORT = 9222
UPLOAD_URL = "https://www.redbubble.com/portfolio/images/new"


def kill_chrome():
    subprocess.run(
        ["powershell", "-Command", "Stop-Process -Name chrome -Force -ErrorAction SilentlyContinue"],
        capture_output=True
    )
    time.sleep(3)


def port_open(host="127.0.0.1", port=9222, timeout=1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def launch_chrome_debug():
    if not CHROME:
        print("  Chrome not found!")
        return False

    kill_chrome()

    cmd = [
        CHROME,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={USER_DATA}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"  Chrome起動: {Path(CHROME).name}")

    # ポートが開くまで最大15秒待機
    for i in range(15):
        if port_open(port=DEBUG_PORT):
            print(f"  CDPポート確認: OK ({i+1}秒)")
            return True
        time.sleep(1)

    print("  CDPポートが開かなかった")
    return False


async def test():
    if not launch_chrome_debug():
        return

    async with async_playwright() as p:
        print(f"  CDP接続中...")
        try:
            browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        except Exception as e:
            print(f"  CDP接続失敗: {e}")
            return

        context = browser.contexts[0] if browser.contexts else None
        if not context:
            print("  コンテキストなし")
            return

        # 新しいタブでアップロードページへ
        page = await context.new_page()
        await page.goto(UPLOAD_URL, wait_until="domcontentloaded", timeout=30000)
        print(f"  URL: {page.url}")

        CF_TITLES = {"just a moment", "shibaraku", "please wait", "checking"}

        for i in range(30):
            try:
                title   = await page.title()
                content = await page.content()
            except Exception:
                await asyncio.sleep(1)
                continue

            has_input = 'type="file"' in content
            print(f"  [{i*2}s] {title[:50]} | file_input={has_input}")

            if has_input:
                print("  SUCCESS: アップロードページ到達！")
                await page.screenshot(path="test_cdp_success.png")
                await browser.close()
                return

            cf_blocked = any(cf in title.lower() for cf in CF_TITLES) or \
                         "challenge" in content[:500].lower()
            if cf_blocked:
                await asyncio.sleep(2)
                continue

            # Cloudflare以外のページ
            if "redbubble" not in page.url:
                print(f"  別サイトに飛んだ: {page.url}")
            await asyncio.sleep(2)

        print("  FAIL: タイムアウト")
        await page.screenshot(path="test_cdp_fail.png")
        await browser.close()


asyncio.run(test())
