"""ContentGenerator のユニットテスト（外部API呼び出しはモック）"""
import pytest
from unittest.mock import MagicMock, patch


def make_generator():
    with patch("google.genai.Client"):
        from modules.content_generator import ContentGenerator
        gen = ContentGenerator.__new__(ContentGenerator)
        gen.client = MagicMock()
        from core.compliance import ComplianceChecker
        gen.compliance = ComplianceChecker()
        return gen


SAMPLE_PRODUCTS = [
    {"Item": {"itemName": "テスト商品A", "itemPrice": 1980, "affiliateUrl": "https://example.com/a"}},
    {"Item": {"itemName": "テスト商品B", "itemPrice": 3200, "itemUrl": "https://example.com/b"}},
]


def test_format_products():
    gen = make_generator()
    result = gen._format_products(SAMPLE_PRODUCTS)
    assert "テスト商品A" in result
    assert "1980" in result
    assert "example.com/a" in result


def test_parse_response_ok():
    gen = make_generator()
    raw = """TITLE: おすすめキッチン用品5選
|||
META: キッチン用品のおすすめを紹介します
|||
CONTENT:
<h2>はじめに</h2><p>本記事はアフィリエイト広告を含みます</p><a href="[PRODUCT_URL_1]">商品1</a>
|||
TAGS: キッチン,料理,おすすめ,楽天,主婦"""
    result = gen._parse_response(raw, SAMPLE_PRODUCTS)
    assert result["title"] == "おすすめキッチン用品5選"
    assert "example.com/a" in result["content"]
    assert "キッチン" in result["tags"]
    assert "広告" in result["content"]  # PR_DISCLOSURE_HTML が付与される


def test_parse_response_missing_title_raises():
    gen = make_generator()
    raw = "META: something\n|||\nCONTENT:\n<p>body</p>\n|||\nTAGS: a,b"
    with pytest.raises(ValueError, match="記事パース失敗"):
        gen._parse_response(raw, SAMPLE_PRODUCTS)


def test_parse_response_rakuten_credit_injected():
    gen = make_generator()
    raw = "TITLE: タイトル\n|||\nMETA: meta\n|||\nCONTENT:\n<p>body</p>\n|||\nTAGS: a"
    result = gen._parse_response(raw, SAMPLE_PRODUCTS)
    assert "webservice.rakuten.co.jp" in result["content"]
