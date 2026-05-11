"""
ventures/shared/optimizer.py — Gemini-powered parameter optimizer
全Ventureで共用。パフォーマンスデータを分析してparamを自動更新する。
"""
import json
import os
import time
from pathlib import Path

try:
    from google import genai
except ImportError:
    print("pip install google-genai")
    exit(1)

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    env_path = Path(__file__).parent.parent.parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip()
                break

client = genai.Client(api_key=API_KEY)


def optimize(venture_name: str, state: dict) -> dict:
    """
    パフォーマンス履歴を分析 → 改善パラメータを返す。
    戻り値: {insight, updated_params, action}
    """
    history = state.get("performance_history", [])
    params = state.get("params", {})
    learnings = state.get("learnings", [])

    if len(history) < 3:
        return {
            "insight": f"データ蓄積中（現在{len(history)}件・3件から分析開始）",
            "updated_params": params,
            "action": "現状維持・データ収集継続",
        }

    prompt = f"""あなたはオンライン副業の収益最適化専門家です。
以下のデータを分析して、具体的なパラメータ改善案を出してください。

事業名: {venture_name}

現在のパラメータ:
{json.dumps(params, ensure_ascii=False, indent=2)}

パフォーマンス履歴（直近{min(len(history), 14)}件）:
{json.dumps(history[-14:], ensure_ascii=False, indent=2)}

過去の学習（直近5件）:
{json.dumps(learnings[-5:], ensure_ascii=False)}

以下のJSONのみ返してください（余分なテキスト不要）:
{{
  "insight": "機能している点・改善すべき点（具体的・1〜2文）",
  "updated_params": {{元のparams構造を維持しつつ、数値や設定を改善したもの}},
  "action": "次に試すべき具体的な1アクション（実行可能・1文）"
}}"""

    for attempt in range(3):
        try:
            resp = client.models.generate_content(model="gemini-flash-latest", contents=prompt)
            text = resp.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            result = json.loads(text)
            # updated_paramsが元のparamsを壊さないようマージ
            merged = {**params, **result.get("updated_params", {})}
            result["updated_params"] = merged
            return result
        except Exception as e:
            if attempt < 2:
                time.sleep(30 * (attempt + 1))
            else:
                return {
                    "insight": f"分析エラー: {str(e)[:80]}",
                    "updated_params": params,
                    "action": "エラー確認後に継続",
                }
