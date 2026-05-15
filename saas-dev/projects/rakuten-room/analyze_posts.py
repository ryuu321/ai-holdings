"""成功投稿パターン分析 — カテゴリ・価格帯・ショップ・URL形式"""
import sys
import re
from pathlib import Path
import pandas as pd

# Windows端末の文字化け防止
sys.stdout.reconfigure(encoding="utf-8")

CSV = Path(__file__).parent / "data" / "products.csv"


def extract_shop(url: str) -> str:
    url = str(url)
    # アフィリエイトURL: pc= パラメータから実URLを取得
    if "hb.afl.rakuten" in url:
        from urllib.parse import urlparse, parse_qs, unquote
        qs = parse_qs(urlparse(url).query)
        actual = qs.get("pc", [""])[0]
        if actual:
            url = unquote(actual)
    m = re.search(r"item\.rakuten\.co\.jp/([^/]+)/", url)
    return m.group(1) if m else ""


def main():
    df = pd.read_csv(CSV, dtype=str)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["posted"] = df["posted"].str.strip().str.lower() == "true"
    df["shop"] = df["url"].apply(extract_shop)

    posted = df[df["posted"]].copy()
    pending = df[~df["posted"]].copy()

    print(f"=== 投稿状況 ===")
    print(f"投稿済み: {len(posted)}件 / 未投稿: {len(pending)}件 / 合計: {len(df)}件\n")

    print("=== カテゴリ別（投稿済み）===")
    print(posted["category"].value_counts().to_string())

    print("\n=== 価格帯（投稿済み）===")
    bins = [0, 500, 1000, 2000, 5000, 10000, float("inf")]
    labels = ["〜500円", "500〜1000円", "1000〜2000円", "2000〜5000円", "5000〜10000円", "10000円〜"]
    posted = posted.copy()
    posted["price_band"] = pd.cut(posted["price"], bins=bins, labels=labels)
    print(posted["price_band"].value_counts().sort_index().to_string())
    print(f"\n価格: 中央値={posted['price'].median():.0f}円 / 平均={posted['price'].mean():.0f}円")

    print("\n=== ショップ別（投稿済み・上位20）===")
    print(posted["shop"].value_counts().head(20).to_string())

    empty_shop_posted = posted[posted["shop"] == ""]
    if len(empty_shop_posted) > 0:
        print(f"\n※shopが空のURL例（投稿済みから5件）:")
        for url in empty_shop_posted["url"].head(5):
            print(f"  {url[:80]}")

    print("\n=== 使用トーン（投稿済み）===")
    if "tone_used" in posted.columns:
        print(posted["tone_used"].value_counts().to_string())

    print("\n=== 未投稿のカテゴリ分布 ===")
    print(pending["category"].value_counts().head(10).to_string())

    print("\n=== 投稿成功ショップの未投稿商品 ===")
    success_shops = set(posted["shop"].dropna().unique()) - {""}
    pending_from_success_shops = pending[pending["shop"].isin(success_shops)]
    print(f"投稿済みショップの未投稿商品: {len(pending_from_success_shops)}件")
    if len(pending_from_success_shops) > 0:
        print("（ROOMに登録されている可能性が高いショップ）")
        print(pending_from_success_shops["shop"].value_counts().to_string())


if __name__ == "__main__":
    main()
