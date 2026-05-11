"""GitHub Actions から呼ばれるスクレイプ実行スクリプト"""
from modules.af_scraper import scrape_af_stats, save_stats

stats = scrape_af_stats(days=30)
if stats:
    save_stats(stats)
    print(f"取得完了: {len(stats)}日分")
else:
    print("スクレイプ失敗（セッションなし or レイアウト変更）")
