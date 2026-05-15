"""auth.jsonをROOM認証に必要なクッキー＋localStorageに絞り込んでbase64化する。"""
import json
import base64
import subprocess
from pathlib import Path

f = Path("auth.json")
data = json.loads(f.read_text(encoding="utf-8"))

keep_domains = [
    "room.rakuten.co.jp",
    "rakuten.co.jp",
    ".rakuten.co.jp",
    "grp01.id.rakuten.co.jp",
    "member.id.rakuten.co.jp",
    "login.account.rakuten.com",
    "account.rakuten.com",
    "grp.rakuten.co.jp",
]

filtered_cookies = [
    c for c in data.get("cookies", [])
    if any(d in c.get("domain", "") for d in keep_domains)
]

# room.rakuten.co.jp の localStorage も保持（セッション状態に必要）
keep_origins = [
    "https://room.rakuten.co.jp",
    "https://grp01.id.rakuten.co.jp",
    "https://login.account.rakuten.com",
]
filtered_origins = [
    o for o in data.get("origins", [])
    if any(o.get("origin", "").startswith(k) for k in keep_origins)
]

slim = json.dumps(
    {"cookies": filtered_cookies, "origins": filtered_origins},
    ensure_ascii=False
)
f.write_text(slim, encoding="utf-8")

b64 = base64.b64encode(slim.encode()).decode()

out = Path("auth_base64.txt")
out.write_text(b64, encoding="utf-8")

print(f"Cookie数: {len(filtered_cookies)}件 / Origin数: {len(filtered_origins)}件 / base64サイズ: {len(b64)} bytes")

try:
    subprocess.run("clip", input=b64.encode(), check=True)
    print("クリップボードにコピーしました → RAKUTEN_AUTH_JSON に登録してください")
except Exception:
    print("auth_base64.txt の内容を RAKUTEN_AUTH_JSON に登録してください")
