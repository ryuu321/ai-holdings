"""undetected-chromedriver でCloudflare突破テスト"""
import time
import json
from pathlib import Path
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

AUTH_FILE  = Path(__file__).parent / "data" / "rb_auth.json"
UPLOAD_URL = "https://www.redbubble.com/portfolio/images/new"


def inject_cookies(driver, auth_file: Path):
    if not auth_file.exists():
        return 0
    cookies = json.loads(auth_file.read_text(encoding="utf-8")).get("cookies", [])
    driver.get("https://www.redbubble.com")
    time.sleep(2)
    for c in cookies:
        try:
            cookie = {
                "name":   c["name"],
                "value":  c["value"],
                "domain": c.get("domain", ".redbubble.com"),
                "path":   c.get("path", "/"),
                "secure": c.get("secure", False),
            }
            driver.add_cookie(cookie)
        except Exception:
            pass
    return len(cookies)


def test():
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1280,900")

    driver = uc.Chrome(options=options, headless=False, version_main=147)

    try:
        n = inject_cookies(driver, AUTH_FILE)
        print(f"  クッキー注入: {n}件")

        print("  アップロードページへ...")
        driver.get(UPLOAD_URL)

        # 最大60秒Cloudflare解決待機
        for i in range(30):
            title = driver.title
            try:
                content = driver.page_source
            except Exception:
                content = ""
            has_input = 'type="file"' in content
            print(f"  [{i*2}s] タイトル: {title[:50]} / file input: {has_input}")

            if has_input:
                print("  SUCCESS: アップロードページ到達！")
                driver.save_screenshot("test_uc_success.png")
                break
            if any(cf in title.lower() for cf in ["just a moment", "challenge", "shibaraku"]):
                time.sleep(2)
                continue
            if "shibaraku" in content[:500] or "just a moment" in content[:500].lower():
                time.sleep(2)
                continue
            # それ以外は別ページ
            print(f"  URL: {driver.current_url}")
            driver.save_screenshot("test_uc_other.png")
            break
        else:
            print("  TIMEOUT: 60秒経過")
            driver.save_screenshot("test_uc_timeout.png")

    finally:
        time.sleep(2)
        driver.quit()


test()
