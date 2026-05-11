"""AI記事生成エンジン（Groq版・マルチテンプレート）"""
import os
import json
import time
from pathlib import Path
from config.settings import settings
from core.compliance import ComplianceChecker
from core.database import Database
from groq import Groq
import asyncio

RAKUTEN_CREDIT_HTML = '''<div style="margin:10px 0">
<a href="https://webservice.rakuten.co.jp/" target="_blank" rel="noopener">
<img src="https://webservice.rakuten.co.jp/img/credit/200709/credit_22121.gif"
     border="0" alt="Rakuten Web Service Center" width="221" height="21"/></a></div>'''

PR_DISCLOSURE_HTML = '''<div style="background:#fff3cd;border:1px solid #ffc107;
padding:10px;margin:10px 0;border-radius:4px;">
⚠️ <strong>本記事には広告（PR）が含まれています。</strong>楽天アフィリエイトプログラムを利用しています。
</div>'''

TEMPLATE_INDEX_FILE = Path(__file__).parent.parent / "data" / "template_index.txt"

TEMPLATES = {
    "ranking": {
        "label": "ランキング形式",
        "instruction": """
記事構成: ランキング形式
- 「第1位〜第5位」と順位をつけて紹介
- 各順位に選んだ理由・特徴・こんな人におすすめを明記
- 冒頭に「この記事でわかること」ボックスを入れる
- 比較表（商品名/価格/特徴）をHTMLテーブルで作成
""",
    },
    "comparison": {
        "label": "徹底比較形式",
        "instruction": """
記事構成: 比較・選び方ガイド形式
- まず「選ぶときの3つのポイント」を解説
- 各商品を同じ評価軸（価格・品質・使いやすさ）で比較
- 「こんな人はAがおすすめ／こんな人はBがおすすめ」と読者を絞る
- HTMLテーブルで比較表を作成
""",
    },
    "story": {
        "label": "ストーリー形式",
        "instruction": """
記事構成: ストーリー・体験談形式
- 冒頭に「こんな悩みはありませんか？」と読者の共感を引く
- 商品との出会いや使った感想をストーリー調で書く
- 「使う前」→「使った後」の変化を具体的に描写
- 感情的な訴求を重視しつつ商品リンクを自然に配置
""",
    },
    "howto": {
        "label": "ハウツー形式",
        "instruction": """
記事構成: ハウツー・活用ガイド形式
- 「〇〇を最大限活用する方法」という切り口
- ステップ形式（Step1, Step2...）で解説
- 各ステップで役立つ商品を自然な流れで紹介
- 「よくある失敗」と「解決策」のセクションを入れる
""",
    },
}

TEMPLATE_ORDER = ["ranking", "comparison", "story", "howto"]


def get_current_template() -> str:
    TEMPLATE_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    idx = int(TEMPLATE_INDEX_FILE.read_text().strip()) if TEMPLATE_INDEX_FILE.exists() else 0
    template = TEMPLATE_ORDER[idx % len(TEMPLATE_ORDER)]
    TEMPLATE_INDEX_FILE.write_text(str(idx + 1))
    return template


class ContentGenerator:
    def __init__(self):
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.compliance = ComplianceChecker()
        self.db = Database()

    def _format_products(self, products: list) -> str:
        lines = []
        for i, p in enumerate(products[:5], 1):
            name  = p.get("Item", {}).get("itemName", "")
            price = p.get("Item", {}).get("itemPrice", "")
            url   = p.get("Item", {}).get("affiliateUrl", "") or p.get("Item", {}).get("itemUrl", "")
            lines.append(f"{i}. {name}（¥{price}）\n   リンク: [PRODUCT_URL_{i}] → {url}")
        return "\n".join(lines)

    def _call_groq(self, prompt: str, retries: int = 3) -> str:
        for attempt in range(retries):
            try:
                response = self.client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                if attempt < retries - 1:
                    wait = 10 * (attempt + 1)
                    print(f"  [WAIT] APIエラー。{wait}秒後にリトライ...")
                    time.sleep(wait)
                else:
                    raise

    async def generate_article(self, niche: str, keyword: str, products: list) -> dict:
        template_key = get_current_template()
        template = TEMPLATES[template_key]
        improvement = self.db.get_latest_prompt_improvement(template_key)

        product_info = self._format_products(products)

        prompt = f"""
あなたは日本語SEOに精通したコンテンツライターです。
楽天アフィリエイト記事をHTML形式で作成してください。

## 必須ルール
- 記事冒頭に「※本記事はアフィリエイト広告を含みます」を入れる
- 誇大表現・虚偽の成果表記は禁止（「確実に」「絶対に」「100%」など）
- 各商品の説明は具体的に異なる内容で書く（コピペ厳禁）
- 商品リンクは必ず <a href="[PRODUCT_URL_n]" target="_blank" rel="nofollow">商品名</a> のHTML形式で書く
- URLを生テキストで貼り付けない

## 記事仕様
- ジャンル: {niche}
- キーワード: {keyword}
- 文字数: 2500〜3500字
- タイトル: 32文字以内・キーワード含む・具体的な数字や特徴を入れる
- H2見出し: 5〜7個
- 末尾にFAQ（3問3答）

{template["instruction"]}

{f"## 追加改善指示（過去の分析より）{chr(10)}{improvement}" if improvement else ""}

## 商品情報（[PRODUCT_URL_n]をそのまま使うこと）
{product_info}

## 出力形式（|||で区切る）

TITLE: （タイトル）
|||
META: （メタディスクリプション120文字以内）
|||
CONTENT:
（HTML形式の本文）
|||
TAGS: タグ1,タグ2,タグ3,タグ4,タグ5
"""
        print(f"  テンプレート: {template['label']}")
        text = self._call_groq(prompt)
        result = self._parse_response(text, products)
        result["template"] = template_key
        return result

    def _parse_response(self, text: str, products: list) -> dict:
        parts = text.split("|||")
        result = {"title": "", "meta_description": "", "content": "", "tags": [], "template": "ranking"}

        for part in parts:
            p = part.strip()
            if p.startswith("TITLE:"):
                result["title"] = p[6:].strip()
            elif p.startswith("META:"):
                result["meta_description"] = p[5:].strip()
            elif "CONTENT:" in p:
                result["content"] = p[p.index("CONTENT:") + 8:].strip()
            elif p.startswith("TAGS:"):
                result["tags"] = [t.strip() for t in p[5:].split(",")][:5]

        for i, prod in enumerate(products[:5], 1):
            url = prod.get("Item", {}).get("affiliateUrl", "") or prod.get("Item", {}).get("itemUrl", "")
            result["content"] = result["content"].replace(f"[PRODUCT_URL_{i}]", url)

        result["content"] = PR_DISCLOSURE_HTML + result["content"] + RAKUTEN_CREDIT_HTML

        if not result["title"]:
            raise ValueError(f"記事パース失敗:\n{text[:300]}")

        return result
