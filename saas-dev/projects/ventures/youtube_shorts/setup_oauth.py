"""
setup_oauth.py — ローカルで1回だけ実行してYouTube refresh_tokenを取得

【事前準備】
Google Cloud Console で OAuth認証情報を開き、
「承認済みのリダイレクトURI」に以下を追加してから実行:
  http://localhost:8080

【実行方法】
  python setup_oauth.py
ブラウザが開くので Google アカウントで許可するだけ。
"""
import json
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 8080
REDIRECT_URI = f"http://localhost:{PORT}"
SCOPE = " ".join([
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/userinfo.email",
])

_code_holder: dict = {}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = params.get("code", [""])[0]
        _code_holder["code"] = code
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "認証成功！このウィンドウを閉じてターミナルに戻ってください。" if code else "エラー：codeが取得できませんでした。"
        self.wfile.write(f"<h2>{msg}</h2>".encode())

    def log_message(self, *args):
        pass  # サーバーログ抑制


def _get_auth_code(client_id: str) -> str:
    auth_url = (
        "https://accounts.google.com/o/oauth2/auth?"
        + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",  # 毎回refresh_tokenを発行させる
        })
    )

    server = HTTPServer(("localhost", PORT), _Handler)

    def _serve():
        server.handle_request()  # 1リクエストだけ処理

    t = threading.Thread(target=_serve, daemon=True)
    t.start()

    print(f"\nブラウザを開いてGoogleアカウントで許可してください...")
    print(f"（自動で開かない場合は手動でアクセス）:\n{auth_url}\n")
    webbrowser.open(auth_url)

    t.join(timeout=120)
    server.server_close()
    return _code_holder.get("code", "")


def _exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    payload = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def main():
    print("=" * 50)
    print("YouTube OAuth2 セットアップ")
    print("=" * 50)
    print()
    print("【事前確認】Google Cloud Console で:")
    print("「承認済みのリダイレクトURI」に追加済みですか?")
    print(f"  → {REDIRECT_URI}")
    print()

    client_id = input("Client ID を貼り付け: ").strip()
    client_secret = input("Client Secret を貼り付け: ").strip()

    code = _get_auth_code(client_id)
    if not code:
        print("\nERROR: 認証コードを取得できませんでした。")
        print("ブラウザで手動認証後、URLの ?code= の値をここに貼り付け:")
        code = input("code: ").strip()

    if not code:
        print("ERROR: code が空です。最初からやり直してください。")
        return

    print("トークン取得中...")
    try:
        data = _exchange_code(client_id, client_secret, code)
    except Exception as e:
        print(f"ERROR: {e}")
        return

    refresh_token = data.get("refresh_token", "")
    if not refresh_token:
        print("ERROR: refresh_token が取得できませんでした。")
        print("Google Cloud Console で「prompt=consent」が有効か確認してください。")
        print(f"レスポンス全体: {data}")
        return

    print()
    print("=" * 50)
    print("成功！GitHub Secrets に以下を登録してください:")
    print("=" * 50)
    # どのアカウントか確認
    try:
        req2 = urllib.request.Request(
            f"https://www.googleapis.com/oauth2/v1/userinfo?access_token={data.get('access_token','')}",
        )
        with urllib.request.urlopen(req2, timeout=10) as r2:
            user_info = json.loads(r2.read())
        print(f"✅ ログインアカウント: {user_info.get('email', '不明')}")
        print()
    except Exception:
        pass

    print(f"YOUTUBE_CLIENT_ID     = {client_id}")
    print(f"YOUTUBE_CLIENT_SECRET = {client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN = {refresh_token}")
    print()
    print("GitHub Secrets 設定場所:")
    print("  https://github.com/ryuu321/ai-holdings/settings/secrets/actions")


if __name__ == "__main__":
    main()
