import json
import subprocess
from pathlib import Path

f = Path("data/af_session.json")
data = json.loads(f.read_text(encoding="utf-8"))

# 楽天系ドメイン（.co.jp と .com 両方）
keep_domains = [
    "rakuten.co.jp",
    "rakuten.com",
    "affiliate.rakuten.co.jp",
    "member.rakuten.co.jp",
    "login.account.rakuten.com",
    "account.rakuten.com",
    "grp.rakuten.co.jp",
]
filtered = [
    c for c in data.get("cookies", [])
    if any(d in c.get("domain", "") for d in keep_domains)
]
slim = json.dumps({"cookies": filtered, "origins": []}, ensure_ascii=False)
f.write_text(slim, encoding="utf-8")

import base64, gzip
b64 = base64.b64encode(gzip.compress(slim.encode())).decode()
print(f"Cookie数: {len(filtered)}件 / base64サイズ: {len(b64)} bytes")

subprocess.run("clip", input=b64.encode(), check=True)
print("クリップボードにコピーしました → RAKUTEN_AF_SESSION_B64 に登録してください")
