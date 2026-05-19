"""Supabase経由でトライアル使用量とアクセスコードを管理する。"""
import os
from supabase import create_client, Client

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_ANON_KEY"]
        _client = create_client(url, key)
    return _client


def get_or_create_user(email: str) -> dict:
    sb = _get_client()
    res = sb.table("trials").select("*").eq("email", email).execute()
    if res.data:
        return res.data[0]
    sb.table("trials").insert({"email": email, "count": 0, "plan": None}).execute()
    return {"email": email, "count": 0, "plan": None}


def increment_count(email: str) -> int:
    sb = _get_client()
    user = get_or_create_user(email)
    new_count = user["count"] + 1
    sb.table("trials").update({"count": new_count}).eq("email", email).execute()
    return new_count


def set_plan(email: str, plan: str) -> None:
    sb = _get_client()
    sb.table("trials").upsert({"email": email, "count": 0, "plan": plan}).execute()


def validate_code(code: str) -> str | None:
    """コードを検証してプラン名を返す。無効なら None。"""
    sb = _get_client()
    res = sb.table("codes").select("plan").eq("code", code).eq("active", True).execute()
    if res.data:
        return res.data[0]["plan"]
    return None


def issue_code(company: str, plan: str) -> str:
    """新しいアクセスコードを発行してコード文字列を返す。"""
    sb = _get_client()
    res = sb.table("codes").insert({"company": company, "plan": plan}).execute()
    return res.data[0]["code"]


def revoke_code(code: str) -> None:
    """コードを無効化する。"""
    sb = _get_client()
    sb.table("codes").update({"active": False}).eq("code", code).execute()
