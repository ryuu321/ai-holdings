"""
generate_emails.py — load_existing_emails の重複除外テスト

実行: pytest shared/gtm/tests/test_generate_emails.py -v
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "outreach"))

from generate_emails import load_existing_emails, _gemini_personalize


def _write_csv(path: Path, emails: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["email", "company_name"])
        writer.writeheader()
        for e in emails:
            writer.writerow({"email": e, "company_name": "テスト"})


class TestLoadExistingEmails:
    def test_both_files_missing_returns_empty(self, tmp_path):
        result = load_existing_emails(tmp_path / "draft.csv", tmp_path / "sent.csv")
        assert result == set()

    def test_reads_draft_file(self, tmp_path):
        draft = tmp_path / "draft.csv"
        _write_csv(draft, ["a@test.co.jp", "b@test.co.jp"])
        result = load_existing_emails(draft, tmp_path / "sent.csv")
        assert result == {"a@test.co.jp", "b@test.co.jp"}

    def test_reads_sent_log(self, tmp_path):
        sent = tmp_path / "sent.csv"
        _write_csv(sent, ["c@test.co.jp"])
        result = load_existing_emails(tmp_path / "draft.csv", sent)
        assert result == {"c@test.co.jp"}

    def test_returns_union_of_both(self, tmp_path):
        draft = tmp_path / "draft.csv"
        sent = tmp_path / "sent.csv"
        _write_csv(draft, ["a@test.co.jp", "b@test.co.jp"])
        _write_csv(sent, ["b@test.co.jp", "c@test.co.jp"])  # b は重複
        result = load_existing_emails(draft, sent)
        assert result == {"a@test.co.jp", "b@test.co.jp", "c@test.co.jp"}

    def test_deduplication_prevents_regeneration(self, tmp_path):
        # 実際のユースケース: draft に30件 + sent_log に5件 → 重複なし35件
        draft = tmp_path / "draft.csv"
        sent = tmp_path / "sent.csv"
        draft_emails = [f"draft{i}@test.co.jp" for i in range(30)]
        sent_emails = [f"sent{i}@test.co.jp" for i in range(5)]
        _write_csv(draft, draft_emails)
        _write_csv(sent, sent_emails)
        result = load_existing_emails(draft, sent)
        assert len(result) == 35
        assert all(e in result for e in draft_emails + sent_emails)


class TestGeminiPersonalizeNoKey:
    def test_empty_api_key_returns_fallback(self):
        text, ok = _gemini_personalize("株式会社テスト", "{company_name}様", "gemini-2.0-flash-lite", "")
        assert ok is False
        assert text == ""
