"""
check_replies.py — get_sent_addresses / mark_replied のユニットテスト

実行: pytest shared/gtm/tests/test_check_replies.py -v
"""
import csv
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "saas-dev" / "projects" / "fudosan-copy" / "outreach"))

import check_replies


def _make_sent_log(tmp_path, rows: list[dict], filename="sent_log.csv") -> Path:
    p = tmp_path / filename
    fields = ["company_name", "email", "subject", "sent_at", "result"]
    with open(p, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return p


class TestGetSentAddresses:
    def test_no_file_returns_empty(self, tmp_path):
        with patch("check_replies.SENT_LOG", tmp_path / "nonexistent.csv"):
            assert check_replies.get_sent_addresses() == {}

    def test_returns_only_sent_result(self, tmp_path):
        log = _make_sent_log(tmp_path, [
            {"company_name": "A社", "email": "a@test.co.jp", "subject": "", "sent_at": "2026-05-19 10:00", "result": "sent"},
            {"company_name": "B社", "email": "b@test.co.jp", "subject": "", "sent_at": "2026-05-19 10:00", "result": "replied"},
            {"company_name": "C社", "email": "c@test.co.jp", "subject": "", "sent_at": "2026-05-19 10:00", "result": "followup"},
        ])
        with patch("check_replies.SENT_LOG", log):
            result = check_replies.get_sent_addresses()
        assert result == {"a@test.co.jp": "A社"}

    def test_multiple_sent_entries(self, tmp_path):
        log = _make_sent_log(tmp_path, [
            {"company_name": "A社", "email": "a@test.co.jp", "subject": "", "sent_at": "2026-05-19 10:00", "result": "sent"},
            {"company_name": "B社", "email": "b@test.co.jp", "subject": "", "sent_at": "2026-05-19 11:00", "result": "sent"},
        ])
        with patch("check_replies.SENT_LOG", log):
            result = check_replies.get_sent_addresses()
        assert set(result.keys()) == {"a@test.co.jp", "b@test.co.jp"}
        assert result["a@test.co.jp"] == "A社"

    def test_empty_file_returns_empty(self, tmp_path):
        log = _make_sent_log(tmp_path, [])
        with patch("check_replies.SENT_LOG", log):
            assert check_replies.get_sent_addresses() == {}


class TestMarkReplied:
    def test_updates_sent_to_replied(self, tmp_path):
        log = _make_sent_log(tmp_path, [
            {"company_name": "A社", "email": "a@test.co.jp", "subject": "件名", "sent_at": "2026-05-19 10:00", "result": "sent"},
            {"company_name": "B社", "email": "b@test.co.jp", "subject": "件名", "sent_at": "2026-05-19 11:00", "result": "sent"},
        ])
        with patch("check_replies.SENT_LOG", log):
            check_replies.mark_replied({"a@test.co.jp"})
        rows = list(csv.DictReader(open(log, encoding="utf-8")))
        assert rows[0]["result"] == "replied"
        assert rows[1]["result"] == "sent"  # B社は変わらない

    def test_already_replied_not_double_marked(self, tmp_path):
        log = _make_sent_log(tmp_path, [
            {"company_name": "A社", "email": "a@test.co.jp", "subject": "件名", "sent_at": "2026-05-19 10:00", "result": "replied"},
        ])
        with patch("check_replies.SENT_LOG", log):
            check_replies.mark_replied({"a@test.co.jp"})
        rows = list(csv.DictReader(open(log, encoding="utf-8")))
        assert rows[0]["result"] == "replied"

    def test_no_file_does_nothing(self, tmp_path):
        with patch("check_replies.SENT_LOG", tmp_path / "nonexistent.csv"):
            check_replies.mark_replied({"a@test.co.jp"})  # エラーにならない

    def test_empty_set_changes_nothing(self, tmp_path):
        log = _make_sent_log(tmp_path, [
            {"company_name": "A社", "email": "a@test.co.jp", "subject": "件名", "sent_at": "2026-05-19 10:00", "result": "sent"},
        ])
        with patch("check_replies.SENT_LOG", log):
            check_replies.mark_replied(set())
        rows = list(csv.DictReader(open(log, encoding="utf-8")))
        assert rows[0]["result"] == "sent"


class TestCheckRepliesNoCredentials:
    def test_no_credentials_returns_empty(self):
        with patch("check_replies.GMAIL_ADDRESS", ""), \
             patch("check_replies.GMAIL_APP_PASSWORD", ""):
            result = check_replies.check_replies({"a@test.co.jp": "A社"})
        assert result == []

    def test_imap_error_returns_empty(self):
        with patch("check_replies.GMAIL_ADDRESS", "test@gmail.com"), \
             patch("check_replies.GMAIL_APP_PASSWORD", "password"), \
             patch("imaplib.IMAP4_SSL", side_effect=Exception("接続失敗")):
            result = check_replies.check_replies({"a@test.co.jp": "A社"})
        assert result == []

    def test_empty_sent_addresses_returns_empty(self):
        with patch("check_replies.GMAIL_ADDRESS", "test@gmail.com"), \
             patch("check_replies.GMAIL_APP_PASSWORD", "password"):
            mock_mail = MagicMock()
            mock_mail.search.return_value = (None, [b""])
            with patch("imaplib.IMAP4_SSL", return_value=mock_mail):
                result = check_replies.check_replies({})
        assert result == []
