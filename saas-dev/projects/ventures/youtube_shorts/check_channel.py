"""どのYouTubeチャンネルにアップロードされているか確認"""
import json
import os
import urllib.request
import urllib.parse

CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

def get_access_token():
    payload = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token", data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read()).get("access_token", "")

token = get_access_token()
if not token:
    print("ERROR: access_token取得失敗")
    raise SystemExit(1)

# tokeninfo でどのGoogleアカウントのトークンか確認
req = urllib.request.Request(
    f"https://oauth2.googleapis.com/tokeninfo?access_token={token}"
)
with urllib.request.urlopen(req, timeout=15) as r:
    info = json.loads(r.read())

print(f"Token email  : {info.get('email', '取得できず')}")
print(f"Scope        : {info.get('scope', '')}")
print(f"Sub (user ID): {info.get('sub', '')}")
