"""トーンローテーションのユニットテスト"""
import pytest
from pathlib import Path
import tempfile, os


def _load_main(tmp_path):
    import sys
    for mod in list(sys.modules.keys()):
        if mod in ("main",):
            del sys.modules[mod]
    with (
        __import__("unittest.mock", fromlist=["patch"]).patch.dict(
            "os.environ", {"RAKUTEN_ID": "dummy", "RAKUTEN_PASSWORD": "dummy"}
        ),
        __import__("unittest.mock", fromlist=["patch"]).patch(
            "main.TONE_INDEX_FILE", tmp_path / "tone_index.txt"
        ),
    ):
        import main as m
        m.TONE_INDEX_FILE = tmp_path / "tone_index.txt"
        return m


def test_tone_rotation_cycles(tmp_path):
    m = _load_main(tmp_path)
    tones = [m.get_current_tone() for _ in range(len(m.TONE_ROTATION) * 2)]
    # 全トーンが一巡する
    unique = set(tones[:len(m.TONE_ROTATION)])
    assert unique == set(m.TONE_ROTATION)


def test_tone_index_persists(tmp_path):
    m = _load_main(tmp_path)
    t1 = m.get_current_tone()
    t2 = m.get_current_tone()
    assert t1 != t2 or len(m.TONE_ROTATION) == 1


def test_tone_col_map_covers_all_rotations(tmp_path):
    m = _load_main(tmp_path)
    for tone in m.TONE_ROTATION:
        assert tone in m.TONE_COL_MAP, f"{tone} が TONE_COL_MAP にない"
