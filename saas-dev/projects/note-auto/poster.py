"""
poster.py — note.com内部APIで記事を投稿（ブラウザ不要）

フロー:
  1. POST /api/v1/text_notes          → note_id / note_key / slug 取得
  2. GET  /api/v3/notes/{key}?draft=true → line_add_friend_access_token 等を取得
  3. POST /api/v1/text_notes/draft_save  → タイトル・本文保存
  4. PUT  /api/v1/text_notes/{id}        → 公開（status=published）
"""
import json
import time
import uuid
import requests
from pathlib import Path

NOTE_BASE     = "https://note.com"
EDITOR_ORIGIN = "https://editor.note.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def login(email: str, password: str, session_file: Path):
    raise RuntimeError(
        "API方式ではブラウザログイン不要。"
        "capture_session.py でセッションを取得してください。"
    )


def _load_cookies(session_file: Path) -> dict:
    """Playwright storage_state JSON からnote.comのcookieを取り出す"""
    state = json.loads(session_file.read_text(encoding="utf-8"))
    # 重複クッキーは最後の値を使う（サーバー更新分を優先）
    cookies = {}
    for c in state.get("cookies", []):
        if "note.com" in c.get("domain", ""):
            cookies[c["name"]] = c["value"]
    return cookies


def _make_session(cookies: dict) -> requests.Session:
    s = requests.Session()
    s.cookies.update(cookies)
    s.headers.update({
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": EDITOR_ORIGIN,
        "referer": EDITOR_ORIGIN + "/",
        "x-requested-with": "XMLHttpRequest",
        "user-agent": UA,
        "accept-language": "ja,en-US;q=0.9,en;q=0.8",
    })
    return s


def _text_to_html(text: str) -> str:
    """テキストをProseMirror形式HTMLに変換（段落IDつき）"""
    parts = []
    for line in text.split("\n"):
        pid = str(uuid.uuid4())
        if line.strip():
            parts.append(f'<p name="{pid}" id="{pid}">{line}</p>')
        else:
            parts.append(f'<p name="{pid}" id="{pid}"><br></p>')
    return "".join(parts) if parts else f'<p name="{uuid.uuid4()}" id="{uuid.uuid4()}"><br></p>'


def post_article(
    title: str,
    free_body: str,
    paid_body: str,
    price: int,
    tags: list,
    email: str = None,
    password: str = None,
    session_file: Path = None,
) -> str:
    if session_file is None:
        session_file = Path(__file__).parent / "note_session.json"

    if not session_file.exists():
        raise RuntimeError(
            f"セッションファイルが見つかりません: {session_file}\n"
            "capture_session.py でセッションを取得してください。"
        )

    cookies = _load_cookies(session_file)
    s = _make_session(cookies)

    # ── Step 1: 新規記事作成 ─────────────────────────────────
    r = s.post(f"{NOTE_BASE}/api/v1/text_notes", json={"template_key": None})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"記事作成失敗 HTTP {r.status_code}: {r.text[:300]}")
    data     = r.json()["data"]
    note_id  = data["id"]
    note_key = data["key"]
    slug     = data.get("slug", f"slug-{note_key}")
    print(f"  [API] 記事作成: id={note_id}, key={note_key}")

    # ── Step 2: draft情報を取得（line_add_friend_access_token等）
    r2 = s.get(
        f"{NOTE_BASE}/api/v3/notes/{note_key}",
        params={"draft": "true", "draft_reedit": "false"},
    )
    draft_data = r2.json().get("data", {}) if r2.status_code == 200 else {}
    line_token = draft_data.get("line_add_friend_access_token", "")

    # ── Step 3: 下書き保存（タイトル・本文）──────────────────
    free_html = _text_to_html(free_body)
    pay_html  = _text_to_html(paid_body) if paid_body else ""
    body_length = len(free_body) + len(paid_body) if paid_body else len(free_body)
    hashtags  = [t.lstrip("#") for t in tags[:5]]

    r3 = s.post(
        f"{NOTE_BASE}/api/v1/text_notes/draft_save",
        params={"id": note_id, "is_temp_saved": "true"},
        json={
            "name":          title,
            "body":          free_html + pay_html,
            "body_length":   body_length,
            "price":         price,
            "hashtag_list":  hashtags,
            "index":         False,
            "is_lead_form":  False,
        },
    )
    if r3.status_code not in (200, 201):
        raise RuntimeError(f"下書き保存失敗 HTTP {r3.status_code}: {r3.text[:300]}")
    print(f"  [API] 下書き保存: {r3.status_code}")
    time.sleep(1)

    # ── Step 4: 公開（PUT）────────────────────────────────────
    # free_body + pay_body を両方送る（separatorなし）
    put_body = {
        "author_ids":                  [],
        "body_length":                 body_length,
        "circle_permissions":          [],
        "disable_comment":             False,
        "discount_campaigns":          [],
        "exclude_ai_learning_reward":  False,
        "exclude_from_creator_top":    False,
        "free_body":                   free_html,
        "hashtags":                    hashtags,
        "image_keys":                  [],
        "index":                       False,
        "is_refund":                   False,
        "lead_form":                   {"is_active": False, "consent_url": ""},
        "limited":                     price > 0,
        "line_add_friend":             {"is_active": False, "keyword": "", "add_friend_url": ""},
        "line_add_friend_access_token": line_token,
        "magazine_ids":                [],
        "magazine_keys":               [],
        "name":                        title,
        "pay_body":                    pay_html if (paid_body and price > 0) else "",
        "price":                       price,
        "pro_coupon_keys":             [],
        "send_notifications_flag":     True,
        "slug":                        slug,
        "status":                      "published",
    }

    r4 = s.put(f"{NOTE_BASE}/api/v1/text_notes/{note_id}", json=put_body)
    if r4.status_code not in (200, 201):
        if price > 0 and r4.status_code == 422:
            print(f"  [WARN] 422詳細: {r4.text[:500]}")
            print(f"  [WARN] 有料記事不可 → 無料で公開")
            put_body["price"]   = 0
            put_body["limited"] = False
            put_body["pay_body"] = ""
            r4 = s.put(f"{NOTE_BASE}/api/v1/text_notes/{note_id}", json=put_body)
        if r4.status_code not in (200, 201):
            raise RuntimeError(f"公開失敗 HTTP {r4.status_code}: {r4.text[:300]}")
    print(f"  [API] 公開完了: {r4.status_code}")

    return f"https://note.com/notes/{note_key}"
