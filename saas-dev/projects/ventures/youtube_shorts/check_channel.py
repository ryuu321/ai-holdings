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

req = urllib.request.Request(
    "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(req, timeout=15) as r:
    data = json.loads(r.read())

for item in data.get("items", []):
    s = item["snippet"]
    print(f"Channel ID   : {item['id']}")
    print(f"Channel Title: {s['title']}")
    print(f"Custom URL   : {s.get('customUrl', 'なし')}")
    print(f"Channel URL  : https://www.youtube.com/channel/{item['id']}")
