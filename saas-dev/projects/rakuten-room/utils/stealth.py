"""Playwright stealth設定"""
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

try:
    from playwright_stealth import stealth_async
    _HAS_STEALTH = True
except ImportError:
    _HAS_STEALTH = False


async def new_stealth_context(browser, storage_state=None):
    ctx = await browser.new_context(
        user_agent=UA,
        viewport={"width": 1280, "height": 800},
        locale="ja-JP",
        timezone_id="Asia/Tokyo",
        storage_state=storage_state,
    )
    await ctx.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP', 'ja', 'en']});
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
    """)
    if _HAS_STEALTH:
        ctx.on("page", lambda page: stealth_async(page))
    return ctx
