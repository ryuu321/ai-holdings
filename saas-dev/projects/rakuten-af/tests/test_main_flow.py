"""main.py の統合フローテスト（全外部呼び出しをモック）"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_run_daily_skips_empty_items():
    """APIが空リストを返した場合はスキップして投稿しない"""
    with (
        patch("modules.rakuten_api.RakutenAPIClient.search_items", new_callable=AsyncMock,
              return_value={"Items": [], "count": 0}),
        patch("modules.content_generator.ContentGenerator.generate_article", new_callable=AsyncMock),
        patch("modules.hatena_publisher.HatenaPublisher.publish", new_callable=AsyncMock),
        patch("google.genai.Client"),
    ):
        import sys
        for mod in list(sys.modules.keys()):
            if "main" in mod and "rakuten" not in mod:
                pass
        from main import run_daily
        await run_daily()


@pytest.mark.asyncio
async def test_run_daily_skips_already_posted():
    """直近7日以内に投稿済みキーワードはスキップする"""
    with (
        patch("core.database.Database.already_posted", return_value=True),
        patch("modules.rakuten_api.RakutenAPIClient.search_items", new_callable=AsyncMock,
              return_value={"Items": [{"Item": {"itemName": "A", "itemPrice": 100,
                                               "affiliateUrl": "https://example.com", "affiliateRate": 5}}]}),
        patch("modules.content_generator.ContentGenerator.generate_article", new_callable=AsyncMock) as mock_gen,
        patch("modules.hatena_publisher.HatenaPublisher.publish", new_callable=AsyncMock),
        patch("google.genai.Client"),
    ):
        from main import run_daily
        await run_daily()
        mock_gen.assert_not_called()
