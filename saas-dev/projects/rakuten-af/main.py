"""
楽天アフィリエイト自動化システム（GitHub Actions版）
実行: python main.py

複数はてなアカウント対応:
  HATENA_ACCOUNT_1_ID / BLOG_ID / API_KEY
  HATENA_ACCOUNT_2_ID / BLOG_ID / API_KEY ... と環境変数を増やすだけでOK

A/Bテスト:
  Strategy A: 多ニッチ（60個）× 7日クールダウン（広範囲SEO）
  Strategy B: 少ニッチ（10個）× 1日クールダウン（特定キーワード深堀り）
"""
import asyncio
import random
from datetime import datetime, timezone
from config.settings import settings
from core.database import Database
from modules.rakuten_api import RakutenAPIClient
from modules.content_generator import ContentGenerator
from modules.hatena_publisher import HatenaPublisher


def pick_strategy() -> str:
    winner = settings.AB_WINNER
    if winner == "A":
        return "A"
    if winner == "B":
        return "B"
    return random.choice(["A", "B"])


def get_niche_pool(strategy: str) -> list:
    return settings.NICHES_A if strategy == "A" else settings.NICHES_B


def get_cooldown(strategy: str) -> int:
    return settings.COOLDOWN_A if strategy == "A" else settings.COOLDOWN_B


async def post_one(db, rakuten, generator, hatena: HatenaPublisher,
                   niche: str, strategy: str, account_id: str) -> bool:
    cooldown = get_cooldown(strategy)
    print(f"\n--- [{strategy}] [{account_id}] {niche} (cooldown:{cooldown}d) ---")

    if db.already_posted(niche, cooldown_days=cooldown):
        print(f"  直近{cooldown}日以内に投稿済み。スキップ。")
        return False

    try:
        print("  [1/3] 商品取得中...")
        data = await rakuten.search_items(keyword=niche, sort="-affiliateRate", hits=10)
        products = data.get("Items", [])
        if not products:
            print("  商品なし。スキップ。")
            return False

        print("  [2/3] 記事生成中（Groq）...")
        article = await generator.generate_article(niche, niche, products)
        print(f"  タイトル: {article['title']}")

        print("  [3/3] はてなブログ投稿中...")
        result = await hatena.publish(
            title=article["title"],
            content=article["content"],
            tags=article.get("tags", [niche]),
        )

        db.record_article(
            post_id=result["post_id"],
            title=article["title"],
            niche=niche,
            keyword=niche,
            post_url=result["post_url"],
            template=article.get("template", "ranking"),
            strategy=strategy,
            account_id=account_id,
        )
        print(f"  投稿完了: {result['post_url']}")
        return True

    except Exception as e:
        print(f"  [ERROR] {e}")
        db.record_error(niche, str(e))
        return False


async def post_for_account(db, rakuten, generator, account: dict, target: int) -> int:
    hatena = HatenaPublisher(account)
    account_id = account["id"]
    success = 0

    strategies = [pick_strategy() for _ in range(target)]
    print(f"\n[{account_id}] 戦略割当: {strategies}")

    for strategy in strategies:
        pool = get_niche_pool(strategy)
        random.shuffle(pool)

        posted = False
        for niche in pool:
            ok = await post_one(db, rakuten, generator, hatena, niche, strategy, account_id)
            if ok:
                success += 1
                posted = True
                break

        if not posted:
            print(f"  [{account_id}][{strategy}] 投稿可能なニッチ枯渇")

    return success


async def run_daily():
    now = datetime.now(timezone.utc)
    accounts = settings.HATENA_ACCOUNTS

    print(f"\n{'='*55}")
    print(f"[rakuten-af] {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"[アカウント数] {len(accounts)}")
    print(f"[AB_WINNER] {settings.AB_WINNER}")

    if not accounts:
        print("[ERROR] はてなアカウントが設定されていません。.envを確認してください。")
        return

    db = Database()
    rakuten = RakutenAPIClient()
    generator = ContentGenerator()

    total_success = 0
    target_per_account = settings.ARTICLES_PER_DAY

    for account in accounts:
        n = await post_for_account(db, rakuten, generator, account, target_per_account)
        total_success += n

    print(f"\n{'='*55}")
    print(f"[完了] 合計{total_success}/{target_per_account * len(accounts)}件 投稿成功")

    ab = db.get_ab_stats(days=14)
    print(f"[AB累計14日] A={ab['A']}件 / B={ab['B']}件")

    weekly = db.get_weekly_summary()
    print(f"[今週] 累計{weekly['article_count']}記事")


if __name__ == "__main__":
    asyncio.run(run_daily())
