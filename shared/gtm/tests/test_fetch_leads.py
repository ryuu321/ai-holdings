"""
fetch_mlit_leads.py — _can_fetch() / _emails_from_html() のユニットテスト

実行: pytest shared/gtm/tests/test_fetch_leads.py -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "saas-dev" / "projects" / "fudosan-copy" / "outreach"))

import fetch_mlit_leads


class TestCanFetch:
    def test_invalid_url_returns_true(self):
        assert fetch_mlit_leads._can_fetch("not-a-url") is True

    def test_robots_read_error_allows_fetch(self):
        fetch_mlit_leads._robots_cache.clear()
        mock_rp = MagicMock()
        mock_rp.read.side_effect = Exception("タイムアウト")
        with patch("urllib.robotparser.RobotFileParser", return_value=mock_rp):
            result = fetch_mlit_leads._can_fetch("https://example.co.jp/page")
        assert result is True

    def test_robots_disallow_blocks_fetch(self):
        fetch_mlit_leads._robots_cache.clear()
        mock_rp = MagicMock()
        mock_rp.read.return_value = None
        mock_rp.can_fetch.return_value = False
        with patch("urllib.robotparser.RobotFileParser", return_value=mock_rp):
            result = fetch_mlit_leads._can_fetch("https://blocked.co.jp/page")
        assert result is False

    def test_robots_allow_permits_fetch(self):
        fetch_mlit_leads._robots_cache.clear()
        mock_rp = MagicMock()
        mock_rp.read.return_value = None
        mock_rp.can_fetch.return_value = True
        with patch("urllib.robotparser.RobotFileParser", return_value=mock_rp):
            result = fetch_mlit_leads._can_fetch("https://allowed.co.jp/page")
        assert result is True

    def test_cache_hit_skips_read(self):
        origin = "https://cached.co.jp"
        mock_rp = MagicMock()
        mock_rp.can_fetch.return_value = True
        fetch_mlit_leads._robots_cache[origin] = mock_rp
        result = fetch_mlit_leads._can_fetch(f"{origin}/page")
        mock_rp.read.assert_not_called()
        assert result is True

    def test_cache_none_allows_fetch(self):
        origin = "https://none-cached.co.jp"
        fetch_mlit_leads._robots_cache[origin] = None
        result = fetch_mlit_leads._can_fetch(f"{origin}/page")
        assert result is True


class TestEmailsFromHtml:
    def test_extracts_basic_email(self):
        html = '<a href="mailto:info@test.co.jp">お問い合わせ</a>'
        assert "info@test.co.jp" in fetch_mlit_leads._emails_from_html(html)

    def test_skips_noreply(self):
        html = "noreply@example.co.jp のメールには返信しないでください"
        assert fetch_mlit_leads._emails_from_html(html) == []

    def test_skips_example_com(self):
        html = "サンプル: info@example.com"
        assert fetch_mlit_leads._emails_from_html(html) == []

    def test_skips_fake_tld_png(self):
        # @2x.png などの画像ファイル誤検知
        html = "background-image: url(logo@2x.png)"
        result = fetch_mlit_leads._emails_from_html(html)
        assert not any(".png" in e for e in result)

    def test_returns_max_2_emails(self):
        html = " ".join(f"info{i}@company{i}.co.jp" for i in range(10))
        result = fetch_mlit_leads._emails_from_html(html)
        assert len(result) <= 2

    def test_deduplicates_same_email(self):
        html = "info@test.co.jp info@test.co.jp info@test.co.jp"
        result = fetch_mlit_leads._emails_from_html(html)
        assert result.count("info@test.co.jp") == 1

    def test_lowercases_email(self):
        html = "INFO@TEST.CO.JP"
        result = fetch_mlit_leaves = fetch_mlit_leads._emails_from_html(html)
        if result:
            assert result[0] == result[0].lower()

    def test_strips_trailing_dot(self):
        html = "contact@test.co.jp."
        result = fetch_mlit_leads._emails_from_html(html)
        if result:
            assert not result[0].endswith(".")

    def test_skips_google_sentry(self):
        html = "sentry@sentry.google.com や no-reply@accounts.google.com"
        result = fetch_mlit_leads._emails_from_html(html)
        assert result == []

    def test_valid_real_estate_email(self):
        html = "お問い合わせは info@yamada-fudosan.co.jp まで"
        result = fetch_mlit_leads._emails_from_html(html)
        assert "info@yamada-fudosan.co.jp" in result
