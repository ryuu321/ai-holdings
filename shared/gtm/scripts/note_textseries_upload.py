"""
TextSeries note.com 自動投稿スクリプト

Usage:
  python note_textseries_upload.py              # 未投稿記事を1件投稿
  python note_textseries_upload.py --limit 3    # 最大3件投稿
  python note_textseries_upload.py --dry-run    # 投稿内容確認のみ
  python note_textseries_upload.py --generate   # 記事生成 + 投稿
  python note_textseries_upload.py --setup-profile  # プロフィール設定（要セッション）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT      = Path(__file__).parent.parent.parent.parent  # ai-holdings/
NOTE_DIR  = ROOT / "shared" / "gtm" / "content" / "note"
PROFILE_DIR = NOTE_DIR / "profile"
POSTER_PY = ROOT / "saas-dev" / "projects" / "note-auto" / "poster.py"
SESSION_FILE = ROOT / "saas-dev" / "projects" / "note-auto" / "note_session_textseries.json"
POSTED_LOG = NOTE_DIR / "posted_log.json"

sys.path.insert(0, str(POSTER_PY.parent))


def load_posted() -> set:
    if POSTED_LOG.exists():
        return set(json.loads(POSTED_LOG.read_text(encoding="utf-8")).get("posted", []))
    return set()


def save_posted(posted: set):
    POSTED_LOG.write_text(
        json.dumps({"posted": sorted(posted)}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def parse_article(md_path: Path) -> dict:
    """markdownファイルから記事データを解析"""
    text = md_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    title = ""
    tags = []
    free_body_lines = []
    paid_body_lines = []
    in_paid = False

    for line in lines:
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("tags:"):
            tags = [t.strip() for t in line[5:].split(",")]
        elif "<!-- 有料部分 -->" in line or "## 有料部分" in line:
            in_paid = True
        elif "<!-- 無料部分 -->" in line or "## 無料部分" in line:
            in_paid = False
        elif line.startswith("#"):
            continue
        else:
            if in_paid:
                paid_body_lines.append(line)
            else:
                free_body_lines.append(line)

    return {
        "title": title or md_path.stem,
        "free_body": "\n".join(free_body_lines).strip(),
        "paid_body": "\n".join(paid_body_lines).strip(),
        "tags": tags or [md_path.stem.replace("_article", ""), "AI", "業務効率化", "中小企業"],
        "price": 0,  # TextSeries記事は無料（集客目的）
    }


def post_one(md_path: Path, dry_run: bool = False) -> str | None:
    article = parse_article(md_path)
    print(f"\n{'='*55}")
    print(f"投稿: {article['title'][:50]}")
    print(f"タグ: {', '.join(article['tags'][:4])}")
    print(f"無料部分: {len(article['free_body'])}字 / 有料部分: {len(article['paid_body'])}字")

    if dry_run:
        print("  [DRY-RUN] 投稿スキップ")
        return "dry-run"

    if not SESSION_FILE.exists():
        print(f"  [ERROR] セッションファイルが見つかりません: {SESSION_FILE}")
        print("  → python saas-dev/projects/note-auto/capture_session.py --file note_session_textseries.json")
        return None

    from poster import post_article
    try:
        url = post_article(
            title=article["title"],
            free_body=article["free_body"],
            paid_body=article["paid_body"],
            price=article["price"],
            tags=article["tags"],
            session_file=SESSION_FILE,
        )
        print(f"  投稿完了: {url}")
        return url
    except Exception as e:
        print(f"  [ERROR] {e}")
        return None


def setup_profile():
    """note.comプロフィールを設定（名前・自己紹介・アイコン・ヘッダー）"""
    import requests

    if not SESSION_FILE.exists():
        print(f"セッションファイルが見つかりません: {SESSION_FILE}")
        return

    from poster import _load_cookies, _make_session
    cookies = _load_cookies(SESSION_FILE)
    s = _make_session(cookies)

    # 現在のユーザー情報を取得
    r = s.get("https://note.com/api/v1/stats/pv?")
    me = s.get("https://note.com/api/v2/creators/me")
    if me.status_code != 200:
        print(f"ユーザー情報取得失敗: {me.status_code}")
        # フォールバック: ユーザーキーを環境変数から取得
        user_key = os.environ.get("NOTE_TEXTSERIES_USER_KEY", "")
    else:
        user_key = me.json().get("data", {}).get("urlname", "")
    print(f"ユーザーキー: {user_key}")

    # プロフィール情報更新
    profile_data = {
        "nickname": "TextSeries｜AI業務ツール",
        "profile": (
            "日本の中小企業・士業事務所向けAIツールを開発・提供しています。\n"
            "社労士・税理士・不動産・建設など103業種のAI書類作成サービス「TextSeries」を運営。\n"
            "全製品、まず無料でお試しいただけます。"
        ),
    }
    r_profile = s.put(
        f"https://note.com/api/v1/users/{user_key}",
        json=profile_data
    )
    print(f"プロフィール更新: {r_profile.status_code}")

    # アイコン画像アップロード
    icon_path = PROFILE_DIR / "icon.png"
    if icon_path.exists():
        with open(icon_path, "rb") as f:
            files = {"user_picture[picture]": ("icon.png", f, "image/png")}
            s.headers.pop("content-type", None)
            r_icon = s.post(
                f"https://note.com/api/v1/user_pictures",
                files=files
            )
        print(f"アイコンアップロード: {r_icon.status_code}")

    # ヘッダー画像アップロード
    header_path = PROFILE_DIR / "header.png"
    if header_path.exists():
        with open(header_path, "rb") as f:
            files = {"user_header[picture]": ("header.png", f, "image/png")}
            r_header = s.post(
                f"https://note.com/api/v1/user_headers",
                files=files
            )
        print(f"ヘッダーアップロード: {r_header.status_code}")

    print("プロフィール設定完了")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=1, help="最大投稿件数")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--generate", action="store_true", help="記事生成してから投稿")
    parser.add_argument("--setup-profile", action="store_true", help="プロフィール設定")
    args = parser.parse_args()

    if args.setup_profile:
        setup_profile()
        return

    # 記事生成
    if args.generate:
        print("記事生成中...")
        result = subprocess.run(
            [sys.executable,
             str(ROOT / "shared" / "gtm" / "scripts" / "generate_note_articles.py"),
             "--limit", "5", "--skip-existing"],
            cwd=str(ROOT)
        )
        if result.returncode != 0:
            print("[ERROR] 記事生成失敗")
            return

    # 投稿済みリスト読み込み
    posted = load_posted()

    # 未投稿の記事を取得
    all_articles = sorted(NOTE_DIR.glob("*_article.md"))
    unposted = [p for p in all_articles if p.name not in posted]

    print(f"記事: {len(all_articles)}件 / 未投稿: {len(unposted)}件")

    if not unposted:
        print("未投稿記事なし。--generate で生成できます。")
        return

    posted_count = 0
    for md_path in unposted[:args.limit]:
        url = post_one(md_path, dry_run=args.dry_run)
        if url and url != "dry-run":
            posted.add(md_path.name)
            save_posted(posted)
            posted_count += 1
            time.sleep(3)

    print(f"\n完了: {posted_count}件投稿")


if __name__ == "__main__":
    main()
