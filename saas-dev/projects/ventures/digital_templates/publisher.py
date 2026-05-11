"""
Gumroad API v2 + note.com dual publisher
Gumroadに商品作成 → note記事で紹介（シナジー）
"""
import json
import os
import sys
import urllib.request
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "note-auto"))


def _load_env(key: str) -> str:
    val = os.environ.get(key, "")
    if val:
        return val
    env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip()
    return ""


# ── Gumroad ──────────────────────────────────────────────

def gumroad_create_product(name: str, description: str, price_yen: int) -> dict | None:
    api_key = _load_env("GUMROAD_API_KEY")
    if not api_key:
        print("  [SKIP] GUMROAD_API_KEY 未設定")
        return None

    # USD換算: ¥300≈$2、¥500≈$4、¥980≈$7
    usd_cents = {300: 200, 500: 400, 980: 700}.get(price_yen, max(100, price_yen * 100 // 150))

    data = urllib.parse.urlencode({
        "access_token": api_key,
        "name": name,
        "description": description,
        "price": usd_cents,
        "currency": "usd",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            "https://api.gumroad.com/v2/products",
            data=data, method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            if result.get("success"):
                product = result["product"]
                return {
                    "id": product["id"],
                    "url": f"https://gumroad.com/l/{product['permalink']}",
                    "permalink": product["permalink"],
                }
    except Exception as e:
        print(f"  [WARN] Gumroad商品作成失敗: {e}")
    return None


def gumroad_upload_file(product_id: str, file_path: Path) -> bool:
    api_key = _load_env("GUMROAD_API_KEY")
    if not api_key or not file_path.exists():
        return False

    boundary = "VentureBoundary2026"
    file_data = file_path.read_bytes()
    mime = "text/csv" if file_path.suffix == ".csv" else "image/jpeg"

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="access_token"\r\n\r\n'
        f"{api_key}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

    try:
        req = urllib.request.Request(
            f"https://api.gumroad.com/v2/products/{product_id}/files",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
            return result.get("success", False)
    except Exception as e:
        print(f"  [WARN] ファイルアップロード失敗: {e}")
        return False


# ── note.com 紹介記事 ──────────────────────────────────────

def post_note_promotion(template_data: dict, gumroad_url: str, account_id: int = 1) -> str | None:
    try:
        from poster import post_article, login
    except ImportError:
        print("  [SKIP] note poster import失敗")
        return None

    email    = _load_env(f"NOTE_EMAIL_{account_id}")
    password = _load_env(f"NOTE_PASSWORD_{account_id}")
    if not email or not password:
        return None

    name  = template_data["name"]
    guide = template_data.get("guide", {})
    intro = template_data.get("note_article_intro", f"{name}を使って管理を楽にしませんか？")
    tags  = template_data.get("tags", ["テンプレート", "スプレッドシート"])

    free_body = f"{intro}\n\n続きにダウンロードリンクと使い方を書きました。"
    paid_body = (
        f"## {name} — 使い方\n\n"
        f"{guide.get('overview', '')}\n\n"
        f"### ダウンロード\n👉 {gumroad_url}\n\n"
        f"### 使い方\n"
        + "\n".join(f"{i}. {s}" for i, s in enumerate(guide.get("steps", []), 1))
        + f"\n\n### 活用ポイント\n"
        + "\n".join(f"- {t}" for t in guide.get("tips", []))
    )

    session_file = Path(__file__).parent.parent.parent / "note-auto" / f"note_session_{account_id}.json"
    try:
        url = post_article(
            title=f"【無料配布】{name}",
            free_body=free_body,
            paid_body=paid_body,
            price=0,
            tags=tags[:5],
            email=email,
            password=password,
            session_file=session_file,
        )
        return url
    except Exception as e:
        print(f"  [WARN] note投稿失敗: {e}")
        return None
