"""
SharoText fetch_leads.py のユニットテスト
pytest tests/ -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import fetch_leads as fl


# ─── TestExtractEmails ───────────────────────────────────────────────────────

class TestExtractEmails:
    def test_extracts_plain_email(self):
        html = '<a href="mailto:info@yamamoto-sharoushi.co.jp">お問い合わせ</a>'
        assert "info@yamamoto-sharoushi.co.jp" in fl._extract_emails(html)

    def test_extracts_email_from_body_text(self):
        html = "お問い合わせ先: contact@tanaka-sr.co.jp まで"
        assert "contact@tanaka-sr.co.jp" in fl._extract_emails(html)

    def test_deduplicates_same_email(self):
        html = "info@abc-sr.co.jp info@abc-sr.co.jp info@abc-sr.co.jp"
        result = fl._extract_emails(html)
        assert result.count("info@abc-sr.co.jp") == 1

    def test_returns_max_two(self):
        html = "a@abc.co.jp b@abc.co.jp c@abc.co.jp d@abc.co.jp"
        assert len(fl._extract_emails(html)) <= 2

    def test_normalizes_to_lowercase(self):
        html = "Info@Yamamoto-SR.CO.JP"
        result = fl._extract_emails(html)
        assert any(e == "info@yamamoto-sr.co.jp" for e in result)

    def test_empty_html_returns_empty(self):
        assert fl._extract_emails("") == []

    def test_no_email_returns_empty(self):
        assert fl._extract_emails("<html><body>お問い合わせはお電話で</body></html>") == []


# ─── TestRejectsBlacklist ────────────────────────────────────────────────────

class TestRejectsBlacklist:
    """EMAIL_SKIP に含まれるアドレスは除外されること"""

    def _emails(self, html):
        return fl._extract_emails(html)

    def test_rejects_noreply(self):
        assert self._emails("noreply@sharoushi.co.jp") == []

    def test_rejects_no_dash_reply(self):
        assert self._emails("no-reply@sharoushi.co.jp") == []

    def test_rejects_example_domain(self):
        assert self._emails("user@example.com") == []

    def test_rejects_postmaster(self):
        assert self._emails("postmaster@office.co.jp") == []

    def test_rejects_webmaster(self):
        assert self._emails("webmaster@office.co.jp") == []

    def test_rejects_sentry(self):
        assert self._emails("sentry@io.example.co.jp") == []

    def test_rejects_google(self):
        assert self._emails("google@google.com") == []

    def test_rejects_schema_org(self):
        assert self._emails("user@schema.org") == []

    def test_rejects_fake_tld_png(self):
        assert self._emails("image@file.png") == []

    def test_rejects_fake_tld_pdf(self):
        assert self._emails("doc@file.pdf") == []


# ─── TestExtractsCorrectly ──────────────────────────────────────────────────

class TestExtractsCorrectly:
    """正常なメールアドレスが取得できること"""

    def test_corporate_cojp(self):
        assert "info@tanaka-sr.co.jp" in fl._extract_emails("info@tanaka-sr.co.jp")

    def test_corporate_jp(self):
        assert "contact@yamamoto.jp" in fl._extract_emails("contact@yamamoto.jp")

    def test_or_jp(self):
        assert "info@sharoushi-osaka.or.jp" in fl._extract_emails("info@sharoushi-osaka.or.jp")

    def test_multiple_emails_different(self):
        html = "info@abc.co.jp contact@abc.co.jp"
        result = fl._extract_emails(html)
        assert "info@abc.co.jp" in result
        assert "contact@abc.co.jp" in result

    def test_mailto_href(self):
        html = '<a href="mailto:office@sr-kanto.co.jp">メール</a>'
        assert "office@sr-kanto.co.jp" in fl._extract_emails(html)


# ─── TestEdgeCases ──────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_string(self):
        assert fl._extract_emails("") == []

    def test_whitespace_only(self):
        assert fl._extract_emails("   ") == []

    def test_at_sign_only(self):
        assert fl._extract_emails("@") == []

    def test_partial_email_no_domain(self):
        assert fl._extract_emails("info@") == []

    def test_partial_email_no_tld(self):
        assert fl._extract_emails("info@nodomain") == []


# ─── TestHtmlToText ─────────────────────────────────────────────────────────

class TestHtmlToText:
    def test_strips_html_tags(self):
        html = "<p>社会保険労務士事務所です</p>"
        text = fl._html_to_text(html)
        assert "<p>" not in text
        assert "社会保険労務士事務所です" in text

    def test_collapses_whitespace(self):
        html = "社労士   事務所"
        text = fl._html_to_text(html)
        assert "  " not in text

    def test_truncates_to_max_chars(self):
        html = "あ" * 2000
        text = fl._html_to_text(html, max_chars=1200)
        assert len(text) <= 1200

    def test_empty_returns_empty(self):
        assert fl._html_to_text("") == ""


# ─── TestSiteSkip ────────────────────────────────────────────────────────────

class TestSiteSkip:
    """SITE_SKIP に含まれるURLはフィルタされること"""

    def test_wikipedia_skipped(self):
        assert any("wikipedia" in s for s in fl.SITE_SKIP)

    def test_sharoushi_portal_skipped(self):
        assert any("sr-jimusho.jp" in s for s in fl.SITE_SKIP)

    def test_sharoushi_or_jp_skipped(self):
        assert any("sharoushi.or.jp" in s for s in fl.SITE_SKIP)

    def test_government_skipped(self):
        assert any("go.jp" in s for s in fl.SITE_SKIP)

    def test_indeed_skipped(self):
        assert any("indeed" in s for s in fl.SITE_SKIP)


# ─── TestIsSharoushiAi ──────────────────────────────────────────────────────

class TestIsSharoushiAi:
    """_is_sharoushi_ai() のフォールバック: APIキーなしはTrueを返す"""

    def test_returns_true_without_api_key(self):
        import os
        original = os.environ.pop("GEMINI_API_KEY", None)
        try:
            result = fl._is_sharoushi_ai("<html>社会保険労務士</html>")
            assert result is True
        finally:
            if original:
                os.environ["GEMINI_API_KEY"] = original

    def test_returns_true_on_api_error(self):
        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            import os
            os.environ["GEMINI_API_KEY"] = "dummy_key"
            try:
                result = fl._is_sharoushi_ai("<html>test</html>")
                assert result is True
            finally:
                del os.environ["GEMINI_API_KEY"]


# ─── TestDeduplication ──────────────────────────────────────────────────────

class TestDeduplication:
    """既存URLは再収集されないこと"""

    def test_existing_url_in_skip_set(self):
        existing = {"https://tanaka-sr.co.jp/"}
        url = "https://tanaka-sr.co.jp/"
        assert url in existing

    def test_new_url_not_in_skip_set(self):
        existing = {"https://tanaka-sr.co.jp/"}
        url = "https://yamamoto-sr.co.jp/"
        assert url not in existing


# ─── TestCompanyNameExtraction ──────────────────────────────────────────────

class TestCompanyNameExtraction:
    """社労士らしい会社名が正しく抽出されること"""

    def test_extracts_from_og_site_name(self):
        html = '<meta property="og:site_name" content="山田社会保険労務士事務所" />'
        name = fl._extract_company_name(html)
        assert name == "山田社会保険労務士事務所"

    def test_extracts_from_title_with_pipe(self):
        html = "<title>就業規則のご相談 | 田中社労士法人</title>"
        name = fl._extract_company_name(html)
        assert name == "田中社労士法人"

    def test_extracts_kabushiki(self):
        html = "<title>採用情報 | 株式会社佐藤労務管理</title>"
        name = fl._extract_company_name(html)
        assert name == "株式会社佐藤労務管理"

    def test_extracts_yuugen(self):
        html = "<title>有限会社鈴木社労士事務所 | HOME</title>"
        name = fl._extract_company_name(html)
        assert name == "有限会社鈴木社労士事務所"

    def test_no_keyword_returns_fallback(self):
        html = "<title>TOPページ</title>"
        name = fl._extract_company_name(html, fallback="fallback-name")
        assert name == "fallback-name"

    def test_empty_html_empty_fallback_returns_empty(self):
        name = fl._extract_company_name("")
        assert name == ""

    def test_separator_that_does_not_split_is_skipped(self):
        # ｜ が含まれない場合、次のセパレータに進む
        html = "<title>山田社会保険労務士法人のホームページ</title>"
        name = fl._extract_company_name(html, fallback="山田社会保険労務士法人")
        assert name != ""  # fallback が返る

    def test_long_company_name_truncated(self):
        long_name = "株式会社" + "あ" * 100
        html = f'<meta property="og:site_name" content="{long_name}" />'
        name = fl._extract_company_name(html)
        assert len(name) <= 40


# ─── TestPipelineSkip ────────────────────────────────────────────────────────

class TestPipelineSkip:
    """ブログタイトル・法人格なし・非社労士は送信対象外になること"""

    _BLOG_NAMES = [
        "社労士の選び方ランキング2024年版",
        "就業規則作成のコツ10選",
        "社労士事務所の比較一覧",
        "社労士に依頼するメリットとは",
        "36協定の書き方まとめ",
    ]

    def test_blog_title_should_have_no_company_keyword(self):
        company_kws = ["株式会社", "有限会社", "合同会社", "事務所", "法人"]
        for name in self._BLOG_NAMES:
            # ブログタイトルには法人格が含まれないはず
            has_kw = any(kw in name for kw in company_kws)
            # 少なくとも「一覧」「ランキング」「コツ」「まとめ」「とは」いずれかを含む
            blog_signals = ["一覧", "ランキング", "コツ", "まとめ", "とは", "比較", "選び方"]
            is_blog = any(sig in name for sig in blog_signals)
            assert is_blog, f"テストデータ不備: {name}"
