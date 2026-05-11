"""
redbubble/main.py — 毎日1〜3件 デザイン生成 → Redbubble自動投稿
"""
import asyncio
import os
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

# .env 読み込み
_env = Path(__file__).parent.parent.parent.parent / ".env"
if _env.exists():
    for _line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in _line and not _line.startswith("#"):
            k, v = _line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from design_gen import next_design
from uploader import upload_design

JST           = timezone(timedelta(hours=9))
UPLOADS_PER_RUN = int(os.environ.get("RB_UPLOADS_PER_RUN", "2"))
RB_EMAIL    = os.environ.get("REDBUBBLE_EMAIL", "")
RB_PASSWORD = os.environ.get("REDBUBBLE_PASSWORD", "")


async def run():
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    print(f"\n{'='*50}")
    print(f"[redbubble] {now}")

    if not RB_EMAIL or not RB_PASSWORD:
        print("REDBUBBLE_EMAIL / REDBUBBLE_PASSWORD が未設定です (.env)")
        return

    success = 0
    for i in range(UPLOADS_PER_RUN):
        print(f"\n--- {i+1}/{UPLOADS_PER_RUN} ---")
        image_path, quote = next_design()
        if image_path is None:
            print("クォート在庫なし")
            break
        print(f"  デザイン生成: {image_path.name}")

        ok = await upload_design(image_path, quote, RB_EMAIL, RB_PASSWORD)
        if ok:
            success += 1
        else:
            print("  アップロード失敗 → 次のデザインへ")

        if i < UPLOADS_PER_RUN - 1:
            wait = random.randint(30, 90)
            print(f"  次まで {wait}秒 待機")
            await asyncio.sleep(wait)

    print(f"\n[完了] {success}/{UPLOADS_PER_RUN}件 投稿成功")


if __name__ == "__main__":
    asyncio.run(run())
