"""research_products のユニットテスト"""
import pytest
import sys
from unittest.mock import patch, MagicMock


# テスト対象関数をモジュールレベルでインポート
def _load_research():
    for mod in list(sys.modules.keys()):
        if "research_products" in mod:
            del sys.modules[mod]
    with patch.dict("os.environ", {"RAKUTEN_APP_ID": "dummy", "GEMINI_API_KEY": "dummy"}):
        import research_products as rp
        return rp


def test_score_high_for_popular_cheap_item():
    rp = _load_research()
    item = {"review_count": 500, "rating": 5.0, "price": 1500, "in_stock": True}
    assert rp._score(item) >= 0.9


def test_score_low_for_unpopular_expensive():
    rp = _load_research()
    item = {"review_count": 0, "rating": 0.0, "price": 10000, "in_stock": False}
    # price_fit=0.1 * weight=0.2 = 0.02 が下限
    assert rp._score(item) < 0.05


def test_score_medium_price_range():
    rp = _load_research()
    item = {"review_count": 100, "rating": 4.0, "price": 6000, "in_stock": True}
    score = rp._score(item)
    assert 0.0 < score < 1.0


def test_fetch_ranking_returns_empty_on_api_error():
    rp = _load_research()
    with patch("requests.get") as mock_get:
        mock_get.return_value.status_code = 500
        mock_get.return_value.text = "Internal Server Error"
        result = rp._fetch_ranking({"keyword": "コスメ 人気", "name": "コスメ"})
        assert result == []


def test_fetch_ranking_parses_items():
    rp = _load_research()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "Items": [
            {"Item": {
                "itemUrl": "https://example.com/1",
                "itemName": "商品A",
                "itemPrice": 2000,
                "reviewAverage": "4.5",
                "reviewCount": "300",
            }}
        ]
    }
    with patch("requests.get", return_value=mock_response):
        result = rp._fetch_ranking({"keyword": "コスメ 人気", "name": "コスメ"})
    assert len(result) == 1
    assert result[0]["name"] == "商品A"
    assert result[0]["price"] == 2000


def test_evidence_url_has_no_id_key():
    """category['id'] を参照しなくなったことを確認"""
    rp = _load_research()
    for cat in rp.CATEGORIES:
        assert "id" not in cat, f"CATEGORIES に 'id' キーが残っています: {cat}"
