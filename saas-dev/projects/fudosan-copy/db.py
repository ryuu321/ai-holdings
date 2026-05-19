"""Supabase経由でトライアル使用量を管理する。"""
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
    """メールアドレスでユーザーを取得または新規作成する。"""
    sb = _get_client()
    res = sb.table("trials").select("*").eq("email", email).execute()
    if res.data:
        return res.data[0]
    sb.table("trials").insert({"email": email, "count": 0, "plan": None}).execute()
    return {"email": email, "count": 0, "plan": None}


def increment_count(email: str) -> int:
    """生成回数を+1してnew_countを返す。"""
    sb = _get_client()
    user = get_or_create_user(email)
    new_count = user["count"] + 1
    sb.table("trials").update({"count": new_count}).eq("email", email).execute()
    return new_count


def set_plan(email: str, plan: str) -> None:
    """プランを設定してカウントをリセットする。"""
    sb = _get_client()
    sb.table("trials").upsert({"email": email, "count": 0, "plan": plan}).execute()
