import os
import re
from google import genai

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

MODEL = "gemini-flash-latest"

_BLACKLIST_PATTERNS = [
    r"[ぁ-ん]{1}[A-Za-z]",
    r"(快適性|快適さ|快適).{0,5}(快適性|快適さ|快適)",
    r"★+",
    r"(満足性|満足度).{0,5}(満足性|満足度)",
]

def _quality_ok(text: str) -> bool:
    for pat in _BLACKLIST_PATTERNS:
        if re.search(pat, text):
            return False
    return True


def _trim_to_limit(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    for i in range(limit, max(0, limit - 20), -1):
        if text[i] in "。、！？\n":
            return text[:i + 1]
    return text[:limit]


def generate(
    *,
    madori: str,
    eki_toho: str,
    chikunensuu: str,
    muki: str,
    menseki: str,
    setsubi: list,
    target: str,
    platform: str,
    platform_info: dict,
    extra: str = "",
) -> dict:
    setsubi_str = "・".join(setsubi) if setsubi else "なし"
    notes = platform_info["notes"]
    catch_max = platform_info["catch_max"]
    body_max = platform_info["body_max"]

    prompt = f"""あなたは不動産ポータルサイトの物件説明文のプロライターです。
以下の物件情報をもとに、{platform}掲載用の物件説明文を作成してください。

【物件情報】
- 間取り: {madori}
- 駅徒歩: {eki_toho}分
- 築年数: {chikunensuu}年
- 向き: {muki}
- 専有面積: {menseki}㎡
- 設備: {setsubi_str}
- ターゲット層: {target}
{f"- 補足: {extra}" if extra else ""}

【出力ルール（必ず守ること）】
1. キャッチコピー: {catch_max}文字以内で1行のみ。数字・具体性を入れる。
2. 物件説明文: {body_max}文字以内。自然な日本語。重複表現禁止。
3. {notes}
4. 絶対禁止: 造語・存在しない漢字・意味不明な複合語（例: 陽当り満足性）の使用。
5. 「、」「。」で読みやすく区切る。1文は60文字以内。
6. 設備のうち実際に魅力的な項目だけ選んで使う（全部列挙しない）。

【出力フォーマット（このまま返す）】
CATCH: （キャッチコピー本文のみ）
BODY: （物件説明文本文のみ）"""

    client = _get_client()

    for attempt in range(3):
        response = client.models.generate_content(model=MODEL, contents=prompt)
        raw = response.text.strip()

        catch_match = re.search(r"CATCH:\s*(.+?)(?:\n|$)", raw)
        body_match = re.search(r"BODY:\s*([\s\S]+?)$", raw, re.MULTILINE)

        if not catch_match or not body_match:
            continue

        catch = _trim_to_limit(catch_match.group(1).strip(), catch_max)
        body = _trim_to_limit(body_match.group(1).strip(), body_max)

        if not _quality_ok(catch) or not _quality_ok(body):
            continue

        return {
            "catch": catch,
            "body": body,
            "catch_len": len(catch),
            "body_len": len(body),
            "catch_max": catch_max,
            "body_max": body_max,
            "ok": True,
        }

    return {"ok": False, "error": "品質基準を満たす文章を生成できませんでした。再試行してください。"}
