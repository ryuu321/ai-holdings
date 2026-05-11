"""
Telegram Bot API クライアント（stdlib onlyで動作）
"""
import json
import os
import urllib.request
from pathlib import Path


def _load_env(key: str) -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


BOT_TOKEN  = _load_env("TELEGRAM_BOT_TOKEN")
CHANNEL_ID = _load_env("TELEGRAM_CHANNEL_ID")


def _api(method: str, payload: dict = None) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload or {}).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def send_message(text: str) -> bool:
    if not BOT_TOKEN or not CHANNEL_ID:
        print("  [SKIP] TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL_ID 未設定")
        return False
    try:
        result = _api("sendMessage", {
            "chat_id": CHANNEL_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        return result.get("ok", False)
    except Exception as e:
        print(f"  [ERROR] Telegram送信失敗: {e}")
        return False


def get_member_count() -> int:
    if not BOT_TOKEN or not CHANNEL_ID:
        return -1
    try:
        result = _api("getChat", {"chat_id": CHANNEL_ID})
        return result.get("result", {}).get("members_count", 0)
    except Exception:
        return -1
