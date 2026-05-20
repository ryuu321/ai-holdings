"""Supabase REST APIを直接呼び出してトライアル使用量とコードを管理する。"""
import os
import urllib.request
import urllib.error
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
    base = os.environ["SUPABASE_URL"].strip().rstrip("/")
    # Secretsに /rest/v1 が含まれている場合は除去
    if base.endswith("/rest/v1"):
        base = base[:-len("/rest/v1")]
    url = f"{base}/rest/v1/{table}"
    if query:
        url += f"?{query}"
    return url


def _debug_url() -> str:
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    return f"{base}/rest/v1/trials"


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
    try:
        rows = _get("trials", f"email=eq.{urllib.parse.quote(email)}&select=*")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        raise RuntimeError(f"GET {_debug_url()} → {e.code}: {body}") from None
    if rows:
        return rows[0]
    try:
        return _post("trials", {"email": email, "count": 0, "plan": None})
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        raise RuntimeError(f"POST {_debug_url()} → {e.code}: {body}") from None


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


def _delete(table: str, query: str) -> int:
    headers = {**_headers(), "Prefer": "return=representation"}
    req = urllib.request.Request(_url(table, query), headers=headers, method="DELETE")
    with urllib.request.urlopen(req, timeout=10) as res:
        result = json.loads(res.read())
        return len(result) if isinstance(result, list) else 0


def delete_user(email: str) -> dict:
    """個人情報開示請求対応: ユーザーのtrialデータを完全削除する"""
    rows = _get("trials", f"email=eq.{urllib.parse.quote(email)}&select=email,count,plan")
    if not rows:
        return {"deleted": False, "reason": "ユーザーが見つかりません"}
    deleted = _delete("trials", f"email=eq.{urllib.parse.quote(email)}")
    return {"deleted": deleted > 0, "email": email}


if __name__ == "__main__":
    import argparse
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=__file__.replace("db.py", "") + "../../../../.env")

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    p_del = sub.add_parser("delete-user", help="個人情報削除請求対応")
    p_del.add_argument("email")

    p_info = sub.add_parser("show-user", help="ユーザー情報確認")
    p_info.add_argument("email")

    args = parser.parse_args()

    if args.cmd == "delete-user":
        result = delete_user(args.email)
        if result["deleted"]:
            print(f"削除完了: {result['email']}")
        else:
            print(f"削除失敗: {result.get('reason', '不明')}")
    elif args.cmd == "show-user":
        rows = _get("trials", f"email=eq.{urllib.parse.quote(args.email)}&select=*")
        print(rows[0] if rows else "ユーザーが見つかりません")
    else:
        parser.print_help()
