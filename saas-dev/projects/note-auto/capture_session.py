"""
capture_session.py — ブラウザを開いて手動ログインし、セッションを保存する
使い方:
  python capture_session.py --account 1
  → ブラウザが開くので手動でログイン → 完了後Enterキーを押す → note_session_1.json が保存される
  → base64エンコードしてGitHub Secretsに登録する
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", type=int, choices=[1, 2, 3], required=True)
    args = parser.parse_args()
    capture(args.account)
