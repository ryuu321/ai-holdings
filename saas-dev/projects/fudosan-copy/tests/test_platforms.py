import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from platforms import PLATFORMS

REQUIRED_KEYS = {"catch_max", "body_max", "catch_label", "body_label", "notes"}


class TestPlatforms:
    def test_all_required_platforms_present(self):
        assert "SUUMO" in PLATFORMS
        assert "at home" in PLATFORMS
        assert "HOMES" in PLATFORMS

    @pytest.mark.parametrize("name", ["SUUMO", "at home", "HOMES"])
    def test_required_keys_exist(self, name):
        assert REQUIRED_KEYS.issubset(PLATFORMS[name].keys()), \
            f"{name} is missing keys: {REQUIRED_KEYS - PLATFORMS[name].keys()}"

    @pytest.mark.parametrize("name", ["SUUMO", "at home", "HOMES"])
    def test_catch_max_is_positive_int(self, name):
        v = PLATFORMS[name]["catch_max"]
        assert isinstance(v, int) and v > 0

    @pytest.mark.parametrize("name", ["SUUMO", "at home", "HOMES"])
    def test_body_max_is_positive_int(self, name):
        v = PLATFORMS[name]["body_max"]
        assert isinstance(v, int) and v > 0

    @pytest.mark.parametrize("name", ["SUUMO", "at home", "HOMES"])
    def test_body_max_greater_than_catch_max(self, name):
        p = PLATFORMS[name]
        assert p["body_max"] > p["catch_max"]

    def test_suumo_catch_max_is_40(self):
        assert PLATFORMS["SUUMO"]["catch_max"] == 40

    def test_suumo_body_max_is_400(self):
        assert PLATFORMS["SUUMO"]["body_max"] == 400

    @pytest.mark.parametrize("name", ["SUUMO", "at home", "HOMES"])
    def test_labels_are_nonempty_strings(self, name):
        p = PLATFORMS[name]
        assert isinstance(p["catch_label"], str) and p["catch_label"]
        assert isinstance(p["body_label"], str) and p["body_label"]

    @pytest.mark.parametrize("name", ["SUUMO", "at home", "HOMES"])
    def test_notes_is_nonempty_string(self, name):
        assert isinstance(PLATFORMS[name]["notes"], str) and PLATFORMS[name]["notes"]
