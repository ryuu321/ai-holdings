"""
generate_emails.py — テスト

実行: pytest shared/gtm/tests/test_generate_emails.py -v

テスト方針:
  _clean_company_name() は「実際に失敗した入力」をすべて網羅すること。
  FudoText 初回送信（2026-05-19）で29件中4件以上が誤送信された原因がこの関数。
  新しい入力パターンを発見したら即テストを追加する。
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "outreach"))

from generate_emails import load_existing_emails, _gemini_personalize, _clean_company_name


def _write_csv(path: Path, emails: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["email", "company_name"])
        writer.writeheader()
        for e in emails:
            writer.writerow({"email": e, "company_name": "テスト"})


# ─── _clean_company_name() ─────────────────────────────────────────────
# この関数に対するテストがゼロだったことが 2026-05-19 誤送信の直接原因。
# 「実際に送信された悪い入力」と「正しく抽出できるべき入力」の両方を必ずカバーする。

class TestCleanCompanyNameBlogTitles:
    """ブログ・記事タイトルは空文字を返すこと（= 生成スキップ）"""

    def test_rejects_tips_article(self):
        # 実際の誤送信: "不動産会社にメールで、物件の問い合せや相談をするときのコツ!"
        assert _clean_company_name("不動産会社にメールで、物件の問い合せや相談をするときのコツ!") == ""

    def test_rejects_ranking_title(self):
        assert _clean_company_name("名古屋でおすすめランキング23選") == ""

    def test_rejects_guide_article(self):
        assert _clean_company_name("不動産仲介会社の選び方ガイド") == ""

    def test_rejects_matome_article(self):
        assert _clean_company_name("賃貸物件の探し方まとめ") == ""

    def test_rejects_toha_article(self):
        assert _clean_company_name("賃貸仲介とは？わかりやすく解説") == ""


class TestCleanCompanyNameBlacklist:
    """名簿業者・営業リスト系は空文字を返すこと"""

    def test_rejects_meibo_vendor(self):
        # 実際の誤送信: "不動産業者法人名簿・営業リスト | 法人リストの名簿エンジン"
        assert _clean_company_name("不動産業者法人名簿・営業リスト | 法人リストの名簿エンジン") == ""

    def test_rejects_eigyo_list(self):
        assert _clean_company_name("営業リスト販売サービス") == ""


class TestCleanCompanyNameCorrectExtraction:
    """正しい法人名が抽出できること"""

    def test_contact_prefix_stripped(self):
        # 実際の誤送信: "お問い合わせ | 東京土地開発株式会社" → 正しくは "東京土地開発株式会社"
        assert _clean_company_name("お問い合わせ | 東京土地開発株式会社") == "東京土地開発株式会社"

    def test_contact_prefix_zenkaku_stripped(self):
        # "お問い合わせ｜協和ビル管理株式会社" → qualify で除外されるが company_name は正しく取れること
        assert _clean_company_name("お問い合わせ｜協和ビル管理株式会社") == "協和ビル管理株式会社"

    def test_long_title_extracts_company(self):
        # "野村不動産パートナーズ株式会社｜ビル・施設管理やマンション管理まで"
        result = _clean_company_name("野村不動産パートナーズ株式会社｜ビル・施設管理やマンション管理まで")
        assert result == "野村不動産パートナーズ株式会社"

    def test_company_name_with_hyphen_separator(self):
        assert _clean_company_name("株式会社山田不動産 - 賃貸仲介") == "株式会社山田不動産"

    def test_kabushiki_at_end(self):
        assert _clean_company_name("さと賃｜株式会社さとう") == "株式会社さとう"

    def test_yugen_extracted(self):
        assert _clean_company_name("お問い合わせ | 有限会社鈴木不動産") == "有限会社鈴木不動産"

    def test_godo_extracted(self):
        assert _clean_company_name("合同会社テスト｜トップページ") == "合同会社テスト"


class TestCleanCompanyNameEdgeCases:
    """境界ケース"""

    def test_empty_string_returns_empty(self):
        assert _clean_company_name("") == ""

    def test_plain_company_name_no_separator(self):
        # セパレータなし・会社名のみ → 末尾パターンで抽出
        result = _clean_company_name("東洋不動産株式会社")
        assert result == "東洋不動産株式会社"

    def test_no_legal_entity_keyword_returns_empty(self):
        # 法人名キーワードなし → スキップ
        assert _clean_company_name("さと賃") == ""

    def test_does_not_truncate_with_raw_fallback(self):
        # raw_name[:20] フォールバックは廃止済み。会社名不明なら必ず空文字
        result = _clean_company_name("これはブログ記事のタイトルです全く関係ない内容")
        assert result == ""


# ─── load_existing_emails() ────────────────────────────────────────────

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
        _write_csv(sent, ["b@test.co.jp", "c@test.co.jp"])
        result = load_existing_emails(draft, sent)
        assert result == {"a@test.co.jp", "b@test.co.jp", "c@test.co.jp"}

    def test_deduplication_prevents_regeneration(self, tmp_path):
        draft = tmp_path / "draft.csv"
        sent = tmp_path / "sent.csv"
        draft_emails = [f"draft{i}@test.co.jp" for i in range(30)]
        sent_emails = [f"sent{i}@test.co.jp" for i in range(5)]
        _write_csv(draft, draft_emails)
        _write_csv(sent, sent_emails)
        result = load_existing_emails(draft, sent)
        assert len(result) == 35
        assert all(e in result for e in draft_emails + sent_emails)


# ─── _gemini_personalize() ────────────────────────────────────────────

class TestGeminiPersonalizeNoKey:
    def test_empty_api_key_returns_fallback(self):
        text, ok = _gemini_personalize("株式会社テスト", "{company_name}様", "gemini-2.0-flash-lite", "")
        assert ok is False
        assert text == ""
