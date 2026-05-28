"""
capture_session.py — ブラウザを開いて手動ログインし、セッションを保存する
使い方:
  python capture_session.py --account 1
  → ブラウザが開くので手動でログイン → 完了後Enterキーを押す → note_session_1.json が保存される
  → base64エンコードしてGitHub Secretsに登録する

  TextSeries専用:
  python capture_session.py --file note_session_textseries.json
  → GitHub Secret名: NOTE_SESSION_TEXTSERIES_B64
"""
import argparse
import base64
import json
import os
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("pip install playwright && playwright install chromium")
    exit(1)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")


def capture(account_id: int):
    session_file = Path(__file__).parent / f"note_session_{account_id}.json"

    print(f"[アカウント{account_id}] ブラウザを開きます...")
    print("note.comにログインして、完全にログインが完了したらターミナルに戻ってEnterを押してください。")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=UA,
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
        )
        page = context.new_page()
        page.goto("https://note.com/login")

        input("\n>>> ログイン完了後にEnterを押してください...")

        context.storage_state(path=str(session_file))
        print(f"\n✓ セッション保存: {session_file}")
        browser.close()

    # base64エンコードして表示
    raw = session_file.read_bytes()
    b64 = base64.b64encode(raw).decode()
    print(f"\n=== GitHub Secrets に登録する値（NOTE_SESSION_{account_id}）===")
    print(b64)
    print(f"\n登録先: https://github.com/ryuu321/ai-holdings/settings/secrets/actions/new")
    print(f"Name:  NOTE_SESSION_{account_id}")
    print(f"Value: 上記のbase64文字列")


def capture_to_file(session_filename: str, secret_name: str, timeout_sec: int = 120):
    session_file = Path(__file__).parent / session_filename
    print(f"ブラウザを開きます... note.comにメールアドレスでログインしてください。")
    print(f"（ログイン完了後、{timeout_sec}秒待つか、ログイン済みを検知したら自動保存します）")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}, locale="ja-JP")
        page = context.new_page()
        page.goto("https://note.com/login")

        # ログイン完了を自動検知（ダッシュボードへのリダイレクト or ホームページ）
        print("ログイン中... 自動検知待機（最大120秒）")
        try:
            # ログイン後はnote.com/のホームかダッシュボードに遷移する
            page.wait_for_url(
                lambda url: "note.com/login" not in url and "note.com" in url,
                timeout=timeout_sec * 1000
            )
            print("✓ ログイン検知。セッション保存中...")
            import time as _time
            _time.sleep(2)  # Cookie確定待ち
        except Exception:
            print("タイムアウト。現在のセッションで保存します...")

        context.storage_state(path=str(session_file))
        print(f"✓ セッション保存: {session_file}")
        browser.close()

    raw = session_file.read_bytes()
    b64 = base64.b64encode(raw).decode()
    b64_file = Path(__file__).parent / "session_b64.txt"
    b64_file.write_text(b64, encoding="utf-8")
    print(f"\n=== GitHub Secret 登録コマンド（PowerShellで実行）===")
    print(f'$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes("{session_file}")); gh secret set {secret_name} --body $b64 --repo ryuu321/ai-holdings')
    print(f"\n（base64値は {b64_file} にも保存済み）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=int, choices=[1, 2, 3], default=None)
    parser.add_argument("--file", type=str, default=None, help="保存ファイル名（例: note_session_textseries.json）")
    args = parser.parse_args()

    if args.file:
        secret_name = args.file.replace(".json", "").replace("note_session_", "NOTE_SESSION_").upper() + "_B64"
        capture_to_file(args.file, secret_name)
    elif args.account:
        capture(args.account)
    else:
        print("--account 1 または --file note_session_textseries.json を指定してください")
