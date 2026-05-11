"""楽天商品リスト生成（Groq版 / API不要）"""
import asyncio
import urllib.parse
from groq import Groq
from config.settings import settings

NICHE_SEARCH_MAP = {
    "食品・グルメ": ["ギフト 食品 人気", "スイーツ 詰め合わせ", "お取り寄せグルメ"],
    "美容・コスメ": ["スキンケア 人気", "化粧水 乾燥肌", "美容液 おすすめ"],
    "家電・パソコン": ["便利グッズ 家電", "ガジェット おすすめ", "スマホ 周辺機器"],
    "ファッション": ["レディース トップス 人気", "メンズ ジャケット", "ワンピース おすすめ"],
    "楽天トラベル": ["温泉 宿 人気", "旅行 ホテル おすすめ", "観光 宿泊"],
    "スポーツ・アウトドア": ["アウトドア グッズ", "スポーツ 用品", "キャンプ 道具"],
    "インテリア・家具": ["インテリア 雑貨", "収納 グッズ", "おしゃれ 家具"],
    "キッズ・ベビー": ["おもちゃ 子供 人気", "知育玩具", "ベビー 育児グッズ"],
    "ペット": ["ペット用品 人気", "犬 グッズ", "猫 おすすめ"],
    "DIY・工具": ["DIY 工具 セット", "電動工具 人気", "修理 道具"],
}


def _build_search_url(keyword: str, affiliate_id: str) -> str:
    encoded_kw = urllib.parse.quote(keyword)
    search_url = f"https://search.rakuten.co.jp/search/mall/{encoded_kw}/"
    if affiliate_id:
        encoded = urllib.parse.quote(search_url, safe="")
        return f"https://hb.afl.rakuten.co.jp/hgc/{affiliate_id}/?pc={encoded}"
    return search_url


class RakutenAPIClient:
    def __init__(self):
        self.affiliate_id = settings.RAKUTEN_AFFILIATE_ID
        self.groq = Groq(api_key=settings.GROQ_API_KEY)

    async def search_items(self, keyword: str, sort: str = "-reviewCount", hits: int = 10, **kwargs) -> dict:
        await asyncio.sleep(0.5)
        searches = NICHE_SEARCH_MAP.get(keyword, [keyword])

        prompt = f"""楽天市場で「{keyword}」カテゴリの人気商品を{hits}個リストアップしてください。

以下のJSON配列形式で出力してください（マークダウン不要、JSONのみ）:
[
  {{"name": "商品名（具体的に）", "price": 価格（整数）, "search": "検索キーワード"}},
  ...
]

条件:
- 実在しそうな具体的な商品名
- 価格は500〜30000円の範囲
- searchは楽天で検索するキーワード（日本語）"""

        try:
            resp = self.groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
            )
            import json, re
            text = resp.choices[0].message.content.strip()
            m = re.search(r"\[[\s\S]+\]", text)
            if not m:
                raise ValueError("JSONが見つからない")
            products_raw = json.loads(m.group())
        except Exception as e:
            print(f"  Groq商品生成エラー: {e} → フォールバック")
            products_raw = [
                {"name": f"{keyword} おすすめ商品{i}", "price": 1000 * i, "search": s}
                for i, s in enumerate(searches[:hits], 1)
            ]

        items = []
        for p in products_raw[:hits]:
            search_kw = p.get("search", keyword)
            url = _build_search_url(search_kw, self.affiliate_id)
            items.append({
                "Item": {
                    "itemName": p.get("name", keyword),
                    "itemPrice": p.get("price", 1000),
                    "itemUrl": url,
                    "affiliateUrl": url,
                    "reviewAverage": 4.0,
                    "reviewCount": 100,
                }
            })

        print(f"  商品生成数: {len(items)}件（Groq）")
        return {"Items": items, "count": len(items)}
