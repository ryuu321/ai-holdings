"""Supabase REST APIを直接呼び出してトライアル使用量とコードを管理する。"""
import os
import urllib.request
import urllib.parse
import json


def _headers() -> dict:
    key = os.environ["SUPABASE_ANON_KEY"].strip()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _url(table: str, query: str = "") -> str:
    base = os.environ["SUPABASE_URL"].rstrip("/")
    url = f"{base}/rest/v1/{table}"
    if query:
        url += f"?{query}"
    return url


def _get(table: str, query: str) -> list:
    req = urllib.request.Request(_url(table, query), headers=_headers())
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def _post(table: str, data: dict) -> dict:
    payload = json.dumps(data).encode()
    req = urllib.request.Request(_url(table), data=payload, headers=_headers(), method="POST")
    with urllib.request.urlopen(req, timeout=10) as res:
        result = json.loads(res.read())
        return result[0] if isinstance(result, list) else result


def _patch(table: str, query: str, data: dict) -> None:
    payload = json.dumps(data).encode()
    req = urllib.request.Request(_url(table, query), data=payload, headers=_headers(), method="PATCH")
    with urllib.request.urlopen(req, timeout=10) as res:
        res.read()


def get_or_create_user(email: str) -> dict:
    rows = _get("trials", f"email=eq.{urllib.parse.quote(email)}&select=*")
    if rows:
        return rows[0]
    return _post("trials", {"email": email, "count": 0, "plan": None})


def increment_count(email: str) -> int:
    user = get_or_create_user(email)
    new_count = user["count"] + 1
    _patch("trials", f"email=eq.{urllib.parse.quote(email)}", {"count": new_count})
    return new_count


def set_plan(email: str, plan: str) -> None:
    rows = _get("trials", f"email=eq.{urllib.parse.quote(email)}&select=email")
    if rows:
        _patch("trials", f"email=eq.{urllib.parse.quote(email)}", {"count": 0, "plan": plan})
    else:
        _post("trials", {"email": email, "count": 0, "plan": plan})


def validate_code(code: str) -> str | None:
    rows = _get("codes", f"code=eq.{urllib.parse.quote(code)}&active=eq.true&select=plan")
    return rows[0]["plan"] if rows else None


def issue_code(company: str, plan: str) -> str:
    result = _post("codes", {"company": company, "plan": plan})
    return result["code"]


def revoke_code(code: str) -> None:
    _patch("codes", f"code=eq.{urllib.parse.quote(code)}", {"active": False})
