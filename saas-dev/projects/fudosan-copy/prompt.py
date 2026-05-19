import os
import re
import time
from google import genai
from domain_knowledge import PROMPT_VERSION, TARGET_APPEAL as _TARGET_APPEAL, CONVERSION_TIPS as _CONVERSION_TIPS

_client = None

def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

MODEL = "gemini-3.1-flash-lite"

_BLACKLIST_PATTERNS = [
    r"[ぁ-ん][a-z]",
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
    body_min = max(100, body_max // 2)
    appeal = _TARGET_APPEAL.get(target, "")
    extra_rule = f"8. 補足情報「{extra}」は必ず物件説明文の本文に具体的に織り込む。" if extra else ""

    prompt = f"""あなたは不動産ポータルサイトの物件説明文のプロライターです。
以下の物件情報をもとに、{platform}掲載用の物件説明文を作成してください。

【物件情報】
- 間取り: {madori}
- 駅徒歩: {eki_toho}分
- 築年数: {chikunensuu}年
- 向き: {muki}
- 専有面積: {menseki}㎡
- 設備: {setsubi_str}
- ターゲット層: {target}（この層が特に気にする点: {appeal}）
{f"- 補足: {extra}" if extra else ""}

{_CONVERSION_TIPS}

【出力ルール（必ず守ること）】
1. キャッチコピー: {catch_max}文字以内で1行のみ。数字・具体性・体言止めを意識する。
2. 物件説明文: {body_min}文字以上{body_max}文字以内。自然な日本語。重複表現禁止。
3. {notes}
4. 絶対禁止: 造語・存在しない漢字・意味不明な複合語・最大級表現・根拠のない断言。
5. 「、」「。」で読みやすく区切る。1文は60文字以内。
6. 設備は「全部列挙」せず、ターゲットに刺さる項目を選んで使う。
7. 生活シーンを1〜2文具体的に描写する（「〇〇できる」「〇〇が楽しめる」）。
{extra_rule}

【出力フォーマット（このまま返す）】
CATCH: （キャッチコピー本文のみ）
BODY: （物件説明文本文のみ）"""

    client = _get_client()

    for attempt in range(3):
        try:
            response = client.models.generate_content(model=MODEL, contents=prompt)
            raw = response.text.strip()
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                if attempt < 2:
                    wait = 2 ** (attempt + 1)  # 2s, 4s
                    time.sleep(wait)
                    continue
                return {"ok": False, "error": "AIが混み合っています（数秒後にもう一度お試しください）。", "error_type": "quota"}
            if attempt < 2:
                continue
            return {"ok": False, "error": "AI接続エラーが発生しました。再試行してください。", "error_type": "api_error"}

        catch_match = re.search(r"CATCH:\s*(.+?)(?:\n|$)", raw)
        body_match = re.search(r"BODY:\s*([\s\S]+?)$", raw, re.MULTILINE)

        if not catch_match or not body_match:
            continue

        catch = _trim_to_limit(catch_match.group(1).strip(), catch_max)
        body = _trim_to_limit(body_match.group(1).strip(), body_max)

        if not _quality_ok(catch) or not _quality_ok(body):
            continue

        if len(body) < body_min:
            continue

        return {
            "catch": catch,
            "body": body,
            "catch_len": len(catch),
            "body_len": len(body),
            "catch_max": catch_max,
            "body_max": body_max,
            "prompt_version": PROMPT_VERSION,
            "ok": True,
        }

    return {"ok": False, "error": "品質基準を満たす文章を生成できませんでした。再試行してください。", "error_type": "quality"}
