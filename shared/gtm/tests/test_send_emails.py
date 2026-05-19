"""
send_emails.py — 時間帯ガード・dry-run・日次上限・重複防止のテスト

実行: pytest shared/gtm/tests/test_send_emails.py -v
"""
import csv
import sys
import time
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "saas-dev" / "projects" / "fudosan-copy" / "outreach"))

import send_emails


DRAFT_ROWS = [
    {
        "company_name": "株式会社テスト不動産",
        "email": "info@test-fudosan.co.jp",
        "subject": "【FudoText】物件説明文の自動生成についてご提案",
        "body": "テスト不動産 ご担当者様\n\nご不要の場合はご返信ください。\n\n真柄 龍聖",
        "url": "https://test-fudosan.co.jp",
        "status": "draft",
        "personalized": "True",
    }
]


class TestJstTimeGate:
    """JST 9:00〜18:00 以外は送信を拒否するテスト"""

    def _run_main_with_utc_hour(self, utc_hour: int) -> str:
        """指定したUTC時刻でmain()を実行してstdout出力を返す"""
        from datetime import datetime as dt, timezone
        fake_utc = MagicMock()
        fake_utc.hour = utc_hour

        out = StringIO()
        with patch("send_emails.datetime") as mock_dt, \
             patch("sys.stdout", out), \
             patch("send_emails.DRAFT_FILE", MagicMock(exists=MagicMock(return_value=False))):
            # now(timezone.utc) → fake_utc, now() → 固定datetime
            mock_dt.now.side_effect = lambda tz=None: fake_utc if tz is not None else dt(2026, 5, 20, 10, 0)
            send_emails.main(dry_run=False, force_send=False)
        return out.getvalue()

    def test_blocks_at_utc0_jst9_boundary(self):
        # UTC 0時 = JST 9時 → 送信可能（DRAFTがなければ早期リターン）
        # ここでは「送信停止」メッセージが出ないことだけ確認
        output = self._run_main_with_utc_hour(0)
        assert "送信停止" not in output

    def test_blocks_at_jst_3am(self):
        # UTC 18時 = JST 3時 → 送信停止
        output = self._run_main_with_utc_hour(18)
        assert "送信停止" in output
        assert "JST" in output

    def test_blocks_at_jst_midnight(self):
        # UTC 15時 = JST 0時 → 送信停止
        output = self._run_main_with_utc_hour(15)
        assert "送信停止" in output

    def test_allows_at_jst_10am(self):
        # UTC 1時 = JST 10時 → 通過（drafts次第）
        output = self._run_main_with_utc_hour(1)
        assert "送信停止" not in output

    def test_allows_at_jst_17(self):
        # UTC 8時 = JST 17時 → 通過
        output = self._run_main_with_utc_hour(8)
        assert "送信停止" not in output

    def test_blocks_at_jst_18_exactly(self):
        # UTC 9時 = JST 18時 → 送信停止（18時は範囲外: 9<=x<18）
        output = self._run_main_with_utc_hour(9)
        assert "送信停止" in output

    def test_force_send_bypasses_time_gate(self):
        # --force-send なら時間外でも止まらない
        from datetime import datetime as dt, timezone
        fake_utc = MagicMock()
        fake_utc.hour = 18  # UTC 18 = JST 3時

        out = StringIO()
        with patch("send_emails.datetime") as mock_dt, \
             patch("sys.stdout", out), \
             patch("send_emails.DRAFT_FILE", MagicMock(exists=MagicMock(return_value=False))):
            mock_dt.now.side_effect = lambda tz=None: fake_utc if tz is not None else dt(2026, 5, 20, 3, 0)
            send_emails.main(dry_run=False, force_send=True)
        assert "送信停止" not in out.getvalue()


class TestDryRun:
    """--dry-run は SMTP 接続を一切行わないテスト"""

    def test_dry_run_does_not_call_send(self):
        tmp_draft = Path(__file__).parent / "_tmp_draft.csv"
        tmp_draft.write_text(
            "company_name,email,subject,body,url,status,personalized\n"
            "株式会社テスト,info@test.co.jp,件名,ご不要の場合はご返信ください。真柄 龍聖,,draft,True\n",
            encoding="utf-8",
        )
        try:
            out = StringIO()
            with patch("send_emails._send") as mock_send, \
                 patch("send_emails.DRAFT_FILE", tmp_draft), \
                 patch("sys.stdout", out):
                send_emails.main(dry_run=True)
            mock_send.assert_not_called()
        finally:
            tmp_draft.unlink(missing_ok=True)

    def test_dry_run_prints_preview(self):
        tmp_draft = Path(__file__).parent / "_tmp_draft2.csv"
        tmp_draft.write_text(
            "company_name,email,subject,body,url,status,personalized\n"
            "株式会社テスト,info@test.co.jp,件名テスト,本文テスト,,draft,True\n",
            encoding="utf-8",
        )
        try:
            out = StringIO()
            with patch("send_emails.DRAFT_FILE", tmp_draft), \
                 patch("sys.stdout", out):
                send_emails.main(dry_run=True)
            output = out.getvalue()
            assert "DRY-RUN" in output
            assert "株式会社テスト" in output
        finally:
            tmp_draft.unlink(missing_ok=True)


class TestSafetyChecks:
    """_check_safety() の警告ロジック"""

    def test_warns_when_fallback_rate_high(self):
        drafts = [
            {"email": f"a{i}@test.co.jp", "body": "ご不要の場合はご返信ください。真柄 龍聖", "personalized": "False"}
            for i in range(10)
        ]
        out = StringIO()
        with patch("sys.stdout", out):
            send_emails._check_safety(drafts, limit=10)
        assert "パーソナライズ失敗率" in out.getvalue()

    def test_warns_when_optout_missing(self):
        drafts = [{"email": "a@test.co.jp", "body": "こんにちは。", "personalized": "True"}]
        out = StringIO()
        with patch("sys.stdout", out):
            result = send_emails._check_safety(drafts, limit=10)
        assert result is False
        assert "オプトアウト" in out.getvalue() or "真柄" in out.getvalue()

    def test_passes_clean_drafts(self):
        drafts = [
            {"email": "a@test.co.jp", "body": "ご不要の場合はご返信ください。真柄 龍聖", "personalized": "True"}
        ]
        result = send_emails._check_safety(drafts, limit=10)
        assert result is True


# ─── 追加テスト ─────────────────────────────────────────────

_SAFE_BODY = "ご不要の場合はご返信ください。真柄 龍聖"


def _make_draft_csv(tmp_path, rows: list[dict], filename="_draft.csv") -> Path:
    p = tmp_path / filename
    fields = ["company_name", "email", "subject", "body", "url", "status", "personalized"]
    with open(p, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return p


def _make_sent_log(tmp_path, rows: list[dict], filename="_sent.csv") -> Path:
    p = tmp_path / filename
    fields = ["company_name", "email", "subject", "sent_at", "result"]
    with open(p, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return p


class TestLoadSent:
    def test_no_file_returns_empty_set(self, tmp_path):
        with patch("send_emails.SENT_LOG", tmp_path / "nonexistent.csv"):
            assert send_emails._load_sent() == set()

    def test_returns_all_emails(self, tmp_path):
        log = _make_sent_log(tmp_path, [
            {"company_name": "A", "email": "a@test.co.jp", "subject": "件名", "sent_at": "2026-05-19 10:00", "result": "sent"},
            {"company_name": "B", "email": "b@test.co.jp", "subject": "件名", "sent_at": "2026-05-19 11:00", "result": "sent"},
        ])
        with patch("send_emails.SENT_LOG", log):
            result = send_emails._load_sent()
        assert result == {"a@test.co.jp", "b@test.co.jp"}


class TestTodaySentCount:
    def test_no_file_returns_zero(self, tmp_path):
        with patch("send_emails.SENT_LOG", tmp_path / "nonexistent.csv"):
            assert send_emails._today_sent_count() == 0

    def test_counts_only_todays_rows(self, tmp_path):
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        log = _make_sent_log(tmp_path, [
            {"company_name": "A", "email": "a@test.co.jp", "subject": "", "sent_at": f"{today} 10:00", "result": "sent"},
            {"company_name": "B", "email": "b@test.co.jp", "subject": "", "sent_at": f"{today} 11:00", "result": "sent"},
            {"company_name": "C", "email": "c@test.co.jp", "subject": "", "sent_at": f"{yesterday} 10:00", "result": "sent"},
        ])
        with patch("send_emails.SENT_LOG", log):
            assert send_emails._today_sent_count() == 2

    def test_empty_file_returns_zero(self, tmp_path):
        log = _make_sent_log(tmp_path, [])
        with patch("send_emails.SENT_LOG", log):
            assert send_emails._today_sent_count() == 0


class TestDailyLimitEnforcement:
    def _make_env(self, tmp_path, today_sent: int, draft_count: int):
        today = datetime.now().strftime("%Y-%m-%d")
        log_rows = [
            {"company_name": f"会社{i}", "email": f"sent{i}@test.co.jp",
             "subject": "", "sent_at": f"{today} 10:00", "result": "sent"}
            for i in range(today_sent)
        ]
        log = _make_sent_log(tmp_path, log_rows)
        draft_rows = [
            {"company_name": f"新会社{i}", "email": f"new{i}@test.co.jp",
             "subject": "件名", "body": _SAFE_BODY, "url": "", "status": "draft", "personalized": "True"}
            for i in range(draft_count)
        ]
        draft = _make_draft_csv(tmp_path, draft_rows)
        return draft, log

    def test_blocks_when_limit_reached(self, tmp_path):
        draft, log = self._make_env(tmp_path, today_sent=30, draft_count=5)
        out = StringIO()
        with patch("send_emails.DRAFT_FILE", draft), \
             patch("send_emails.SENT_LOG", log), \
             patch("send_emails.GMAIL_ADDRESS", "test@gmail.com"), \
             patch("send_emails.GMAIL_APP_PASSWORD", "password"), \
             patch("send_emails._send") as mock_send, \
             patch("sys.stdout", out):
            send_emails.main(limit=30, dry_run=False, force_send=True)
        mock_send.assert_not_called()
        assert "上限" in out.getvalue()

    def test_sends_only_remaining_quota(self, tmp_path):
        draft, log = self._make_env(tmp_path, today_sent=28, draft_count=5)
        with patch("send_emails.DRAFT_FILE", draft), \
             patch("send_emails.SENT_LOG", log), \
             patch("send_emails.GMAIL_ADDRESS", "test@gmail.com"), \
             patch("send_emails.GMAIL_APP_PASSWORD", "password"), \
             patch("send_emails._send", return_value=True) as mock_send, \
             patch("time.sleep"):
            send_emails.main(limit=30, dry_run=False, force_send=True)
        assert mock_send.call_count == 2  # 30 - 28 = 残り2件


class TestDuplicatePrevention:
    def test_skips_already_sent_emails(self, tmp_path):
        log = _make_sent_log(tmp_path, [
            {"company_name": "既送信", "email": "existing@test.co.jp",
             "subject": "", "sent_at": "2026-05-15 10:00", "result": "sent"},
        ])
        draft = _make_draft_csv(tmp_path, [
            {"company_name": "既送信", "email": "existing@test.co.jp",
             "subject": "件名", "body": _SAFE_BODY, "url": "", "status": "draft", "personalized": "True"},
            {"company_name": "新規", "email": "new@test.co.jp",
             "subject": "件名", "body": _SAFE_BODY, "url": "", "status": "draft", "personalized": "True"},
        ])
        with patch("send_emails.DRAFT_FILE", draft), \
             patch("send_emails.SENT_LOG", log), \
             patch("send_emails.GMAIL_ADDRESS", "test@gmail.com"), \
             patch("send_emails.GMAIL_APP_PASSWORD", "password"), \
             patch("send_emails._send", return_value=True) as mock_send, \
             patch("time.sleep"):
            send_emails.main(dry_run=False, force_send=True)
        assert mock_send.call_count == 1
        assert mock_send.call_args[0][0] == "new@test.co.jp"

    def test_skips_status_sent_drafts(self, tmp_path):
        log = _make_sent_log(tmp_path, [])
        draft = _make_draft_csv(tmp_path, [
            {"company_name": "送信済み", "email": "done@test.co.jp",
             "subject": "件名", "body": _SAFE_BODY, "url": "", "status": "sent", "personalized": "True"},
            {"company_name": "新規", "email": "new@test.co.jp",
             "subject": "件名", "body": _SAFE_BODY, "url": "", "status": "draft", "personalized": "True"},
        ])
        with patch("send_emails.DRAFT_FILE", draft), \
             patch("send_emails.SENT_LOG", log), \
             patch("send_emails.GMAIL_ADDRESS", "test@gmail.com"), \
             patch("send_emails.GMAIL_APP_PASSWORD", "password"), \
             patch("send_emails._send", return_value=True) as mock_send, \
             patch("time.sleep"):
            send_emails.main(dry_run=False, force_send=True)
        assert mock_send.call_count == 1
        assert mock_send.call_args[0][0] == "new@test.co.jp"
