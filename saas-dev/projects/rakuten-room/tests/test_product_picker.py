"""product_picker のユニットテスト（tempファイル使用）"""
import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch


def _make_picker(tmp_path):
    csv = tmp_path / "products.csv"
    with patch("utils.product_picker.CSV_PATH", csv):
        import importlib, sys
        for mod in list(sys.modules.keys()):
            if "product_picker" in mod:
                del sys.modules[mod]
        import utils.product_picker as pp
        pp.CSV_PATH = csv
        return pp, csv


SAMPLE_ROW = {
    "url": "https://example.com/item1",
    "name": "テスト商品",
    "category": "コスメ・美容",
    "buyer_persona": "20〜30代女性",
    "price": "1980",
    "rating": "4.5",
    "review_count": "200",
    "score": "0.75",
    "copy_short_polite": "短文丁寧",
    "copy_short_casual": "短文カジュアル",
    "copy_short_mom": "短文ママ",
    "copy_medium_polite": "中文丁寧",
    "copy_medium_casual": "中文カジュアル",
    "copy_medium_mom": "中文ママ",
    "copy_long_polite": "長文丁寧",
    "copy_long_casual": "長文カジュアル",
    "copy_long_mom": "長文ママ",
    "hashtags": "#楽天ROOM,#コスメ",
    "evidence_url": "https://example.com",
    "captured_at": "2026-04-21 10:00",
    "posted": "False",
    "posted_at": "",
    "tone_used": "",
}


def test_append_and_count(tmp_path):
    pp, csv = _make_picker(tmp_path)
    pp.append_products([SAMPLE_ROW])
    assert pp.count_pending() == 1


def test_duplicate_skip(tmp_path):
    pp, csv = _make_picker(tmp_path)
    pp.append_products([SAMPLE_ROW])
    pp.append_products([SAMPLE_ROW])  # 同じURL → スキップ
    assert pp.count_pending() == 1


def test_get_pending_returns_unposted(tmp_path):
    pp, csv = _make_picker(tmp_path)
    pp.append_products([SAMPLE_ROW])
    pending = pp.get_pending(5)
    assert len(pending) == 1
    assert pending.iloc[0]["url"] == SAMPLE_ROW["url"]


def test_mark_posted(tmp_path):
    pp, csv = _make_picker(tmp_path)
    pp.append_products([SAMPLE_ROW])
    pp.mark_posted(SAMPLE_ROW["url"], "short_casual")
    assert pp.count_pending() == 0
    df = pp.load_products()
    row = df[df["url"] == SAMPLE_ROW["url"]].iloc[0]
    assert row["posted"] == "True"
    assert row["tone_used"] == "short_casual"
