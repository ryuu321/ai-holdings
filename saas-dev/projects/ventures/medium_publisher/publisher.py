"""
Multi-platform publisher: Dev.to + Hashnode
Dev.to APIキー: dev.to/settings/extensions → API Keys
Hashnode APIキー: hashnode.com/account/developer → API Keys
Unsplash: unsplash.com/developers → free 50req/hr, no approval needed for demo
"""
import json
import os
import urllib.request
import urllib.parse
from pathlib import Path

_UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

# ジャンル → Unsplash検索キーワードマッピング
_GENRE_QUERIES = {
    "AI & Productivity": "technology productivity workspace",
    "Personal Finance":  "finance money investment coins",
    "Career Development": "career office professional success",
}
_DEFAULT_QUERY = "technology abstract digital"


def _fetch_cover_image(genre: str) -> str:
    """Unsplash APIからジャンルに合った画像URLを取得。失敗時は空文字。"""
    if not _UNSPLASH_KEY:
        return ""
    query = _GENRE_QUERIES.get(genre, _DEFAULT_QUERY)
    encoded = urllib.parse.quote(query)
    url = f"https://api.unsplash.com/photos/random?query={encoded}&orientation=landscape&w=1000"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Client-ID {_UNSPLASH_KEY}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
            return data.get("urls", {}).get("regular", "")
    except Exception:
        return ""


def _get_api_key() -> str:
    key = os.environ.get("DEVTO_API_KEY", "")
    if key:
        return key
    env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DEVTO_API_KEY="):
                return line.split("=", 1)[1].strip()
    return ""


def publish_hashnode(title: str, body: str, tags: list, api_key: str, publication_id: str,
                     canonical_url: str = "") -> str:
    """Hashnodeにマークダウン記事を投稿。URLを返す。"""
    if not api_key or not publication_id:
        return ""
    query = """
    mutation PublishPost($input: PublishPostInput!) {
      publishPost(input: $input) {
        post { id url }
      }
    }"""
    clean_tags = [{"slug": t.lower().replace(" ", "-")[:20], "name": t[:20]} for t in tags[:5] if t.strip()]
    variables = {
        "input": {
            "publicationId": publication_id,
            "title": title,
            "contentMarkdown": body,
            "tags": clean_tags,
        }
    }
    if canonical_url:
        variables["input"]["originalArticleURL"] = canonical_url
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        "https://gql.hashnode.com/",
        data=payload,
        headers={"Authorization": api_key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
        return result["data"]["publishPost"]["post"]["url"]


def publish(title: str, subtitle: str, body: str, tags: list, api_key: str,
            canonical_url: str = "", genre: str = "") -> str:
    full_body = f"*{subtitle}*\n\n{body}" if subtitle else body
    # dev.toのタグは英数字・ハイフンのみ・最大4つ
    clean_tags = [t.lower().replace(" ", "")[:20] for t in tags[:4] if t.strip()]

    article_payload: dict = {
        "title": title,
        "body_markdown": full_body,
        "published": True,
        "tags": clean_tags,
    }
    if canonical_url:
        article_payload["canonical_url"] = canonical_url

    cover_image = _fetch_cover_image(genre)
    if cover_image:
        article_payload["main_image"] = cover_image

    payload = json.dumps({"article": article_payload}).encode("utf-8")

    req = urllib.request.Request(
        "https://dev.to/api/articles",
        data=payload,
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
        return result["url"]
