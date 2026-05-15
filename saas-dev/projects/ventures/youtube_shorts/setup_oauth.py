"""
setup_oauth.py — ローカルで1回だけ実行してYouTube refresh_tokenを取得

使い方:
1. Google Cloud Console (console.cloud.google.com) でプロジェクト作成
2. YouTube Data API v3 を有効化
3. OAuth2認証情報 (Desktop app type) を作成 → client_id & client_secret をメモ
4. このスクリプトを実行: python setup_oauth.py
5. 表示されたURLをブラウザで開いてGoogleアカウントで認証
6. リダイレクトURLの ?code= の値をコピーしてここに貼り付け
7. 表示されたrefresh_tokenをGitHub Secretsに YOUTUBE_REFRESH_TOKEN として保存

その他のSecrets:
- YOUTUBE_CLIENT_ID
- YOUTUBE_CLIENT_SECRET
- YOUTUBE_REFRESH_TOKEN
"""
import json
import urllib.request
import urllib.parse

CLIENT_ID     = input("YouTube Client ID: ").strip()
CLIENT_SECRET = input("YouTube Client Secret: ").strip()

auth_url = (
    "https://accounts.google.com/o/oauth2/auth?"
    + urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
        "scope": "https://www.googleapis.com/auth/youtube.upload",
        "response_type": "code",
        "access_type": "offline",
    })
)
print(f"\n1. このURLをブラウザで開いてください:\n{auth_url}\n")
code = input("2. 認証後に表示されたコードを貼り付け: ").strip()

payload = urllib.parse.urlencode({
    "code": code,
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "redirect_uri": "urn:ietf:wg:oauth:2.0:oob",
    "grant_type": "authorization_code",
}).encode("utf-8")

req = urllib.request.Request(
    "https://oauth2.googleapis.com/token", data=payload,
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)
with urllib.request.urlopen(req) as r:
    data = json.loads(r.read())

print("\n=== GitHub Secretsに保存してください ===")
print(f"YOUTUBE_CLIENT_ID:     {CLIENT_ID}")
print(f"YOUTUBE_CLIENT_SECRET: {CLIENT_SECRET}")
print(f"YOUTUBE_REFRESH_TOKEN: {data.get('refresh_token', 'ERROR - refresh_token未取得')}")
