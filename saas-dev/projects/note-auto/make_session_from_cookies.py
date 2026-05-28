"""
Chrome DevToolsからコピーしたCookieでセッションファイルを作成する

使い方:
  1. Chromeでnote.comにログイン
  2. F12 → Application → Cookies → https://note.com
  3. DevToolsのConsoleタブで以下を実行してコピー:
     copy(document.cookie)
  4. このスクリプトを実行して貼り付け

  python make_session_from_cookies.py --file note_session_textseries.json
"""
import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

HERE = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="note_session_textseries.json")
    args = parser.parse_args()

    out_file = HERE / args.file
    secret_name = args.file.replace(".json", "").replace("note_session_", "NOTE_SESSION_").upper() + "_B64"

    print("=" * 55)
    print("Chrome DevTools手順:")
    print("  1. note.comをChromeで開いてログイン済みか確認")
    print("  2. F12 → Consoleタブ")
    print('  3. copy(document.cookie) を実行（クリップボードにコピーされる）')
    print("  4. ここに貼り付けてEnter（2回Enterで確定）")
    print("=" * 55)
    print()

    lines = []
    print("クッキー文字列を貼り付け > ", end="", flush=True)
    while True:
        line = input()
        if line == "" and lines:
            break
        if line:
            lines.append(line)

    cookie_str = " ".join(lines).strip()
    if not cookie_str:
        print("キャンセルしました")
        return

    # cookie_str を解析して storage_state 形式に変換
    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append({
            "name": name,
            "value": value,
            "domain": ".note.com",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": True,
            "sameSite": "None",
        })

    if not cookies:
        print("クッキーが解析できませんでした")
        return

    storage_state = {
        "cookies": cookies,
        "origins": [],
    }

    out_file.write_text(json.dumps(storage_state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ セッション保存: {out_file}  ({len(cookies)}件のクッキー)")

    # base64エンコード
    raw = out_file.read_bytes()
    b64 = base64.b64encode(raw).decode()

    print(f"\n=== GitHub Secret登録コマンド ===")
    print(f"以下をターミナルで実行（! をつけてここから実行可）:")
    print(f'gh secret set {secret_name} --body "{b64[:20]}..." --repo ryuu321/ai-holdings')
    print()
    print("または手動登録:")
    print(f"  Name:  {secret_name}")
    b64_file = HERE / "session_b64.txt"
    b64_file.write_text(b64, encoding="utf-8")
    print(f"  Value: {b64_file} の内容をコピペ")


if __name__ == "__main__":
    main()
