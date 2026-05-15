"""
Qiita自動投稿 — note-bizの日本語記事をQiitaに配信
毎日実行。未投稿記事を1件選んでQiita APIで公開。
APIトークン: qiita.com/settings/applications → 個人用アクセストークン発行
"""
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from datetime import datetime, timezone

_ROOT     = Path(__file__).parent.parent.parent.parent.parent
NOTE_OUT  = _ROOT / "note-biz" / "output"
STATE_FILE = Path(__file__).parent / "state.json"

QIITA_TOKEN = os.environ.get("QIITA_ACCESS_TOKEN", "")

# ジャンル別タグ
GENRE_TAGS = {
    "AI副業・ChatGPT活用系": ["ChatGPT", "AI", "副業", "生産性向上", "プログラミング"],
    "お金・節約・投資入門系": ["資産運用", "NISA", "節約", "投資", "お金"],
    "就活・転職・キャリア系": ["転職", "キャリア", "就活", "面接", "年収"],
}
DEFAULT_TAGS = ["AI", "副業", "生産性"]


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"posted_titles": [], "total_published": 0}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _detect_genre(title: str, content: str) -> str:
    if any(k in title + content for k in ["ChatGPT", "AI", "副業", "在宅", "自動"]):
        return "AI副業・ChatGPT活用系"
    if any(k in title + content for k in ["NISA", "投資", "節約", "貯金", "家計", "iDeCo"]):
        return "お金・節約・投資入門系"
    if any(k in title + content for k in ["転職", "キャリア", "就活", "面接", "年収"]):
        return "就活・転職・キャリア系"
    return "AI副業・ChatGPT活用系"


def _clean_body(content: str) -> str:
    """Qiita向けにマークダウンを整形。有料部分マーカーを除去。"""
    body = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    body = re.sub(r"\n{3,}", "\n\n", body)
    # Gumroad CTAを追加
    cta = (
        "\n\n---\n\n"
        "## 関連リソース\n\n"
        "📊 毎日AI投資シグナルを無料配信中 → [Telegramチャンネル](https://t.me/+yUiqVJi2uNFiOTA1)\n\n"
        "🛠️ AIを使った生産性向上ツールキット → [Gumroad](https://ryuumg.gumroad.com/l/akikab)\n"
    )
    return body.strip() + cta


def _pick_article(posted_titles: list) -> dict | None:
    """未投稿で有料部分がある記事を選択。"""
    files = sorted(NOTE_OUT.glob("**/*.md"), reverse=True) if NOTE_OUT.exists() else []
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
            lines   = content.splitlines()
            title   = lines[0].lstrip("# ").strip() if lines else ""
            if not title or title in posted_titles:
                continue
            if "<!-- 有料部分 -->" not in content:
                continue
            parts = content.split("<!-- 有料部分 -->")
            paid_body = parts[1].strip() if len(parts) > 1 else ""
            if len(paid_body) < 300:
                continue
            free_body = ""
            if "<!-- 無料部分 -->" in parts[0]:
                free_body = parts[0].split("<!-- 無料部分 -->")[1].strip()
            full_body = f"# {title}\n\n{free_body}\n\n{paid_body}"
            return {
                "title": title,
                "body": full_body,
                "source_file": f.name,
            }
        except Exception:
            continue
    return None


def publish_qiita(title: str, body: str, tags: list) -> str:
    """Qiita APIで記事を投稿。URLを返す。"""
    qiita_tags = [{"name": t[:20], "versions": []} for t in tags[:5]]
    payload = json.dumps({
        "title":   title,
        "body":    body,
        "private": False,
        "tags":    qiita_tags,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://qiita.com/api/v2/items",
        data=payload,
        headers={
            "Authorization":  f"Bearer {QIITA_TOKEN}",
            "Content-Type":   "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
        return result.get("url", "")


def main():
    print(f"\n{'='*50}")
    print("[qiita_publisher] Qiita投稿 開始")

    if not QIITA_TOKEN:
        print("  [SKIP] QIITA_ACCESS_TOKEN 未設定")
        print("  → qiita.com/settings/applications でトークン発行後、GitHubシークレットに追加")
        return

    state = _load_state()
    article = _pick_article(state.get("posted_titles", []))
    if not article:
        print("  [SKIP] 未投稿記事なし")
        return

    title  = article["title"]
    body   = _clean_body(article["body"])
    genre  = _detect_genre(title, body)
    tags   = GENRE_TAGS.get(genre, DEFAULT_TAGS)

    print(f"  記事: {title}")
    print(f"  ジャンル: {genre} / タグ: {tags}")

    try:
        url = publish_qiita(title, body, tags)
        print(f"  投稿完了: {url}")
        state.setdefault("posted_titles", []).append(title)
        state["total_published"] = state.get("total_published", 0) + 1
        state["last_posted_at"] = datetime.now(timezone.utc).isoformat()
        _save_state(state)
        print(f"[完了] 通算{state['total_published']}記事")
    except Exception as e:
        print(f"  [ERROR] {e}")


if __name__ == "__main__":
    main()
