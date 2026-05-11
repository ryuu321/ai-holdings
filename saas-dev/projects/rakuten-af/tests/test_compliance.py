"""ComplianceChecker のユニットテスト"""
import pytest
from core.compliance import ComplianceChecker

checker = ComplianceChecker()

VALID_CONTENT = """<div>※本記事はアフィリエイト広告を含みます</div>
<p>おすすめ商品を紹介します</p>
<a href="https://hb.afl.rakuten.co.jp/xxx" rel="nofollow sponsored">商品A</a>
<a href="https://webservice.rakuten.co.jp/" >credit</a>"""

INVALID_CONTENT = "<p>おすすめ商品です。確実に効果があります。</p>"


@pytest.mark.asyncio
async def test_valid_article_passes():
    result = await checker.check_article({"title": "タイトル20字以内", "content": VALID_CONTENT})
    assert result["passed"] is True
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_missing_disclosure_fails():
    result = await checker.check_article({"title": "タイトル", "content": INVALID_CONTENT})
    assert result["passed"] is False
    assert any("PR" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_prohibited_expression_warns():
    content = VALID_CONTENT + "<p>確実に痩せます</p>"
    result = await checker.check_article({"title": "タイトル", "content": content})
    assert any("確実に" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_long_title_warns():
    long_title = "あ" * 61
    result = await checker.check_article({"title": long_title, "content": VALID_CONTENT})
    assert any("タイトル" in w for w in result["warnings"])


def test_sns_post_missing_pr():
    result = checker.validate_sns_post("おすすめ商品です！", "twitter")
    assert result["passed"] is False


def test_sns_post_with_pr():
    result = checker.validate_sns_post("#PR おすすめ商品です！", "twitter")
    assert result["passed"] is True
