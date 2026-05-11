"""
デジタルテンプレート生成: Gemini → CSV + カテゴリ管理
"""
import json
import os
import time
import csv
import io
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

ALL_CATEGORIES = [
    {"name": "月間家計簿テンプレート",       "price": 300,  "genre": "節約・家計管理"},
    {"name": "副業収入トラッカー",           "price": 500,  "genre": "AI副業・ChatGPT活用系"},
    {"name": "NISA積立計画シート",           "price": 500,  "genre": "投資・資産形成"},
    {"name": "習慣トラッカー30日版",         "price": 300,  "genre": "仕事術・生産性"},
    {"name": "転職活動管理シート",           "price": 500,  "genre": "就活・転職・キャリア系"},
    {"name": "節約目標達成プランナー",        "price": 300,  "genre": "節約・家計管理"},
    {"name": "副業アイデア評価マトリクス",     "price": 500,  "genre": "AI副業・ChatGPT活用系"},
    {"name": "年間収支・資産管理シート",       "price": 980,  "genre": "投資・資産形成"},
    {"name": "週間タスク優先度管理表",        "price": 300,  "genre": "仕事術・生産性"},
    {"name": "投資ポートフォリオ記録シート",   "price": 980,  "genre": "投資・資産形成"},
    {"name": "ChatGPTプロンプト管理ノート",   "price": 500,  "genre": "AI副業・ChatGPT活用系"},
    {"name": "固定費削減チェックリスト",       "price": 300,  "genre": "節約・家計管理"},
    {"name": "面接対策・自己PR整理シート",     "price": 500,  "genre": "就活・転職・キャリア系"},
    {"name": "読書記録・学び管理テンプレート", "price": 300,  "genre": "仕事術・生産性"},
    {"name": "副業月次KPIダッシュボード",     "price": 980,  "genre": "AI副業・ChatGPT活用系"},
]


def pick_next(generated_names: list, params: dict) -> dict | None:
    priority = params.get("priority_genres", [])

    # priority genreを先に
    if priority:
        for cat in ALL_CATEGORIES:
            if cat["name"] not in generated_names and cat["genre"] in priority:
                return cat

    # それ以外
    for cat in ALL_CATEGORIES:
        if cat["name"] not in generated_names:
            return cat

    return None


def generate(category: dict, params: dict) -> dict:
    per_run = params.get("templates_per_run", 1)

    prompt = f"""あなたはGoogleスプレッドシート専門のテンプレートデザイナーです。

テンプレート名: {category['name']}
ジャンル: {category['genre']}
価格: ¥{category['price']}

以下を生成してください（JSONのみ）:
{{
  "name": "{category['name']}",
  "price": {category['price']},
  "genre": "{category['genre']}",
  "gumroad_description": "商品説明（250文字以上・悩み→解決→購買意欲の順）",
  "csv_headers": ["列ヘッダー1", "列ヘッダー2", ...（6〜10列）],
  "csv_sample_rows": [
    ["サンプル値", "サンプル値", ...],
    ["サンプル値", "サンプル値", ...],
    ["サンプル値", "サンプル値", ...],
    ["サンプル値", "サンプル値", ...],
    ["サンプル値", "サンプル値", ...]
  ],
  "guide": {{
    "overview": "このテンプレートで何ができるか（2〜3文）",
    "steps": ["使い方ステップ1", "ステップ2", "ステップ3", "ステップ4"],
    "tips": ["活用ポイント1", "活用ポイント2", "活用ポイント3"]
  }},
  "note_article_intro": "noteの記事無料部分（150文字・このテンプレートで解決できる悩みを語りかける）",
  "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5"]
}}"""

    for attempt in range(4):
        try:
            resp = client.models.generate_content(
                model="gemini-flash-latest",
                contents=prompt,
                config={"temperature": 0.6}
            )
            text = resp.text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            return json.loads(text)
        except Exception as e:
            err = str(e)
            if attempt < 3 and ("429" in err or "503" in err or "RESOURCE_EXHAUSTED" in err):
                wait = 60 * (attempt + 1)
                print(f"  [WAIT] {wait}s リトライ...")
                time.sleep(wait)
            else:
                raise


def build_csv(template_data: dict) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(template_data["csv_headers"])
    for row in template_data.get("csv_sample_rows", []):
        # 列数を合わせる
        padded = row + [""] * max(0, len(template_data["csv_headers"]) - len(row))
        writer.writerow(padded[:len(template_data["csv_headers"])])
    # 入力用空行を20行追加
    for _ in range(20):
        writer.writerow([""] * len(template_data["csv_headers"]))
    return output.getvalue().encode("utf-8-sig")  # Excel/Sheets対応 BOM付きUTF-8
