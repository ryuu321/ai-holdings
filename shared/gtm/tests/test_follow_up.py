"""
follow_up.py — _get_followup_targets() の 7日カットオフテスト

実行: pytest shared/gtm/tests/test_follow_up.py -v
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "saas-dev" / "projects" / "fudosan-copy" / "outreach"))

from follow_up import _get_followup_targets


def _row(email: str, days_ago: int, result: str = "sent") -> dict:
    """sent_at が N日前の sent_log 行を作るヘルパー"""
    sent_at = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M")
    return {"company_name": f"会社_{email}", "email": email, "subject": "件名",
            "sent_at": sent_at, "result": result}


class TestGetFollowupTargets:
    def test_empty_log_returns_empty(self):
        assert _get_followup_targets([], days=7) == []

    def test_includes_email_sent_7_days_ago(self):
        log = [_row("old@test.co.jp", days_ago=7)]
        targets = _get_followup_targets(log, days=7)
        assert len(targets) == 1
        assert targets[0]["email"] == "old@test.co.jp"

    def test_excludes_email_sent_6_days_ago(self):
        # 7日未満はまだフォローアップしない
        log = [_row("recent@test.co.jp", days_ago=6)]
        targets = _get_followup_targets(log, days=7)
        assert targets == []

    def test_excludes_already_followed_up(self):
        log = [
            _row("a@test.co.jp", days_ago=10, result="sent"),
            _row("a@test.co.jp", days_ago=3, result="followup"),  # フォロー済み
        ]
        targets = _get_followup_targets(log, days=7)
        assert targets == []

    def test_excludes_replied(self):
        log = [
            _row("b@test.co.jp", days_ago=10, result="sent"),
            {"company_name": "会社B", "email": "b@test.co.jp",
             "subject": "", "sent_at": "2026-05-10 10:00", "result": "replied"},
        ]
        targets = _get_followup_targets(log, days=7)
        assert targets == []

    def test_excludes_followup_failed(self):
        log = [
            _row("c@test.co.jp", days_ago=10, result="sent"),
            _row("c@test.co.jp", days_ago=3, result="followup_failed"),
        ]
        targets = _get_followup_targets(log, days=7)
        assert targets == []

    def test_deduplicates_same_email(self):
        # 同じメアドが sent_log に複数回あっても1件だけ
        log = [
            _row("dup@test.co.jp", days_ago=10, result="sent"),
            _row("dup@test.co.jp", days_ago=8, result="sent"),
        ]
        targets = _get_followup_targets(log, days=7)
        assert len(targets) == 1

    def test_mixed_log(self):
        log = [
            _row("old@test.co.jp", days_ago=10),       # 対象
            _row("recent@test.co.jp", days_ago=3),      # 除外（日数不足）
            _row("replied@test.co.jp", days_ago=10, result="replied"),  # 除外（返信済み）
            _row("followedup@test.co.jp", days_ago=10, result="followup"),  # 除外（フォロー済み）
        ]
        targets = _get_followup_targets(log, days=7)
        assert len(targets) == 1
        assert targets[0]["email"] == "old@test.co.jp"

    def test_custom_days_threshold(self):
        # --days 3 ならば3日前も対象
        log = [_row("a@test.co.jp", days_ago=3)]
        assert len(_get_followup_targets(log, days=3)) == 1
        assert len(_get_followup_targets(log, days=4)) == 0
