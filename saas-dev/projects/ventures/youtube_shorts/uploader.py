"""
uploader.py
YouTube Data API v3 で動画をアップロード。
OAuth2 refresh_token を使って access_token を取得。
"""
import json
import os
import time
import urllib.request
import urllib.parse
from pathlib import Path

YOUTUBE_CLIENT_ID     = os.environ.get("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


def _get_access_token() -> str:
    """refresh_tokenからaccess_tokenを取得。"""
    if not (YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN):
        return ""
    payload = urllib.parse.urlencode({
        "client_id": YOUTUBE_CLIENT_ID,
        "client_secret": YOUTUBE_CLIENT_SECRET,
        "refresh_token": YOUTUBE_REFRESH_TOKEN,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(TOKEN_URL, data=payload,
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read()).get("access_token", "")
    except Exception as e:
        print(f"  [Token ERROR] {e}")
        return ""


def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "26",  # 26 = Howto & Style
) -> str:
    """動画をアップロード。成功したらYouTube URLを返す。"""
    access_token = _get_access_token()
    if not access_token:
        print("  [SKIP] YouTube OAuth未設定")
        return ""

    # 1. Resumable uploadを初期化
    metadata = json.dumps({
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:15],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }).encode("utf-8")

    init_url = f"{UPLOAD_URL}?uploadType=resumable&part=snippet,status"
    file_size = video_path.stat().st_size
    req = urllib.request.Request(
        init_url, data=metadata,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(file_size),
        },
    )
    req.get_method = lambda: "POST"
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            upload_location = r.headers.get("Location", "")
    except Exception as e:
        print(f"  [YouTube init ERROR] {e}")
        return ""

    if not upload_location:
        print("  [YouTube ERROR] upload_location取得失敗")
        return ""

    # 2. 動画データをアップロード
    video_data = video_path.read_bytes()
    upload_req = urllib.request.Request(
        upload_location, data=video_data,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "video/mp4",
            "Content-Length": str(file_size),
        },
    )
    upload_req.get_method = lambda: "PUT"
    try:
        with urllib.request.urlopen(upload_req, timeout=300) as r:
            result = json.loads(r.read())
        video_id = result.get("id", "")
        if video_id:
            url = f"https://www.youtube.com/watch?v={video_id}"
            print(f"  YouTube投稿完了: {url}")
            return url
    except Exception as e:
        print(f"  [YouTube upload ERROR] {e}")

    return ""
