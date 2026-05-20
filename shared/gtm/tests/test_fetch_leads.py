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


class TestExtractCompanyName:
    """_extract_company_name() — 法人格なしは空文字を返すこと"""

    def test_og_site_name_with_legal_entity(self):
        html = '<meta property="og:site_name" content="株式会社山田不動産" />'
        assert fetch_mlit_leads._extract_company_name(html) == "株式会社山田不動産"

    def test_og_site_name_without_legal_entity_returns_empty(self):
        # og:site_nameに法人格なし → 空文字
        html = '<meta property="og:site_name" content="北九州の不動産" />'
        assert fetch_mlit_leads._extract_company_name(html) == ""

    def test_title_separator_extracts_legal_entity(self):
        html = "<title>お問い合わせ | 株式会社東洋不動産</title>"
        result = fetch_mlit_leads._extract_company_name(html)
        assert result == "株式会社東洋不動産"

    def test_no_legal_entity_in_title_returns_empty(self):
        html = "<title>名古屋でおすすめランキング23選</title>"
        assert fetch_mlit_leads._extract_company_name(html) == ""


class TestFetchMlitCompanies:
    """_fetch_mlit_companies() — MLIT HTMLから会社名を抽出"""

    def test_extracts_kabushiki_from_td(self):
        html = "<td>株式会社山田不動産</td><td>東京都</td>"
        with patch("fetch_mlit_leads._fetch_page", return_value=html), \
             patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.read.return_value = html.encode()
            mock_resp.headers.get_content_charset.return_value = "utf-8"
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp
            result = fetch_mlit_leads._fetch_mlit_companies(13, count=10)
        assert "株式会社山田不動産" in result

    def test_network_error_returns_empty(self):
        with patch("urllib.request.urlopen", side_effect=Exception("接続失敗")):
            result = fetch_mlit_leads._fetch_mlit_companies(13)
        assert result == []

    def test_no_companies_in_html_returns_empty(self):
        html = "<html><body>検索結果なし</body></html>"
        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.read.return_value = html.encode()
            mock_resp.headers.get_content_charset.return_value = "utf-8"
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp
            result = fetch_mlit_leads._fetch_mlit_companies(13)
        assert result == []


class TestDomainFiltering:
    """_process_brave_results() — co.jp / .jp 以外はスキップ"""

    def _make_result(self, url: str) -> dict:
        return {"url": url, "title": "株式会社テスト不動産", "description": ""}

    def test_non_jp_domain_skipped(self):
        results = [self._make_result("https://example.com/contact")]
        existing = set()
        import io, csv as csv_mod
        buf = io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=["company_name", "email", "url"])
        with patch("fetch_mlit_leads._fetch_page", return_value=""), \
             patch("fetch_mlit_leads._can_fetch", return_value=True):
            added = fetch_mlit_leads._process_brave_results(results, existing, writer, buf)
        assert added == 0

    def test_co_jp_domain_processed(self):
        html = 'info@yamada-fudosan.co.jp <meta property="og:site_name" content="株式会社山田不動産" />'
        results = [self._make_result("https://yamada-fudosan.co.jp/")]
        existing = set()
        import io, csv as csv_mod
        buf = io.StringIO()
        writer = csv_mod.DictWriter(buf, fieldnames=["company_name", "email", "url"])
        with patch("fetch_mlit_leads._fetch_page", return_value=html), \
             patch("fetch_mlit_leads._can_fetch", return_value=True), \
             patch("time.sleep"):
            added = fetch_mlit_leads._process_brave_results(results, existing, writer, buf)
        assert added == 1
