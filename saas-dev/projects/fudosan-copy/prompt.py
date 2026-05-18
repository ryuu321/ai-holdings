import os
import re
from google import genai

PROMPT_VERSION = "v1.1"  # ドメイン知識強化版

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

# ターゲット層ごとの訴求ポイント（成約率に寄与する観点）
_TARGET_APPEAL = {
    "ファミリー":       "広さ・収納・学区・公園・安全性・将来的なゆとり",
    "カップル・DINKS":  "おしゃれさ・二人の時間・利便性・キッチンや浴室のグレード感",
    "単身者（社会人）": "通勤利便性・セキュリティ・収納・帰ってからくつろげる空間",
    "単身者（学生）":   "駅近・コスパ・シンプルな生活のしやすさ",
    "シニア":           "バリアフリー・静かさ・買い物のしやすさ・管理の楽さ",
    "投資家":           "利回り・管理費・エリアの賃貸需要・表面利回りの根拠",
}

# 成約率を上げると言われる表現パターン（業界知見）
_CONVERSION_TIPS = """
【成約率を上げる表現の原則】
- 数字を使う: 「広い」より「58㎡」「収納3か所」「徒歩7分」
- 生活シーンを描く: 「朝の光が差し込む」「帰宅後すぐシャワーを浴びられる」
- ネガティブを先に消す: 駅遠なら「静かな住環境」、築古なら「リノベ済みで新築同様の内装」
- ターゲットの不安を先に解消する: ファミリーには「〇〇小学校区」、単身には「オートロック」
- 「です・ます」より体言止めで余韻を残す（キャッチコピーは特に）
- 禁止: 「最高」「最良」「一番」などの最大級表現（景品表示法リスク）
- 禁止: 根拠のない断言（「絶対に〇〇」「必ず〇〇」）
"""


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
                return {"ok": False, "error": "APIの利用上限に達しました。しばらく待ってから再試行してください。", "error_type": "quota"}
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
