"""Database のユニットテスト（インメモリSQLite）"""
import pytest
from unittest.mock import patch
import tempfile, os


@pytest.fixture
def db(tmp_path):
    with patch.dict(os.environ, {"DB_PATH": str(tmp_path / "test.db")}):
        # settings は環境変数から読む
        import importlib, sys
        for mod in list(sys.modules.keys()):
            if "rakuten" in mod or "config" in mod or "core" in mod:
                del sys.modules[mod]
        with patch("config.settings.Settings.DB_PATH", str(tmp_path / "test.db")):
            from core.database import Database
            return Database()


def test_record_and_already_posted(tmp_path):
    with patch("config.settings.Settings.DB_PATH", str(tmp_path / "test.db")):
        import sys
        for mod in list(sys.modules.keys()):
            if "database" in mod:
                del sys.modules[mod]
        from core.database import Database
        d = Database()

        assert not d.already_posted("テストキーワード")
        d.record_article("post_001", "タイトル", "美容", "テストキーワード", "https://example.com")
        assert d.already_posted("テストキーワード")


def test_weekly_summary(tmp_path):
    with patch("config.settings.Settings.DB_PATH", str(tmp_path / "test2.db")):
        import sys
        for mod in list(sys.modules.keys()):
            if "database" in mod:
                del sys.modules[mod]
        from core.database import Database
        d = Database()

        for i in range(3):
            d.record_article(str(i), f"タイトル{i}", "食品", f"kw{i}", "")
        summary = d.get_weekly_summary()
        assert summary["article_count"] == 3


def test_record_error(tmp_path):
    with patch("config.settings.Settings.DB_PATH", str(tmp_path / "test3.db")):
        import sys
        for mod in list(sys.modules.keys()):
            if "database" in mod:
                del sys.modules[mod]
        from core.database import Database
        d = Database()
        d.record_error("test_job", "something went wrong")
        row = d.conn.execute("SELECT * FROM errors").fetchone()
        assert row["job_name"] == "test_job"
