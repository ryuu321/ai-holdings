"""
qualify_leads.py — score_lead() のユニットテスト + qualify() の統合テスト

実行: pytest shared/gtm/tests/test_qualify_leads.py -v
"""
import csv
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "leads"))

from qualify_leads import score_lead, qualify

# テスト用最小設定（FudoText想定）
CFG = {
    "icp": {
        "target_keywords": ["不動産", "賃貸", "仲介"],
        "good_domain_suffixes": ["co.jp", "jp"],
        "bad_domain_suffixes": ["gmail.com", "yahoo.co.jp"],
        "exclude_keywords": ["求人", "転職", "協会", "組合", "ランキング", "一覧"],
    },
    "scoring": {
        "target_keyword_hit": 30,
        "good_domain": 20,
        "has_company_type": 20,
        "bad_domain_penalty": -20,
        "exclude_keyword_penalty": -50,
    },
}


class TestPlaceholderDomains:
    def test_sample_co_jp_rejected(self):
        score, reasons = score_lead("テスト不動産", "info@sample.co.jp", "https://sample.co.jp", CFG)
        assert score == 0
        assert "placeholder" in reasons[0]

    def test_mail_jp_rejected(self):
        score, _ = score_lead("株式会社テスト", "contact@mail.jp", "https://test.co.jp", CFG)
        assert score == 0

    def test_example_com_rejected(self):
        score, _ = score_lead("株式会社テスト", "info@example.com", "https://test.co.jp", CFG)
        assert score == 0

    def test_noreply_rejected(self):
        score, _ = score_lead("株式会社テスト", "noreply@noreply.com", "https://test.co.jp", CFG)
        assert score == 0


class TestTargetKeywords:
    def test_keyword_in_url(self):
        # URL に日本語キーワードが含まれる場合（Brave 検索結果のタイトルやパス）
        score, reasons = score_lead("株式会社ABC", "info@abc.co.jp", "https://abc.co.jp/不動産/物件", CFG)
        assert score >= 30
        assert any("ターゲットキーワード" in r for r in reasons)

    def test_keyword_in_company_name(self):
        score, _ = score_lead("株式会社不動産ABC", "info@abc.co.jp", "https://abc.co.jp", CFG)
        assert score >= 30

    def test_no_keyword_no_bonus(self):
        score, reasons = score_lead("株式会社ABC", "info@abc.co.jp", "https://abc.co.jp", CFG)
        assert not any("ターゲットキーワード" in r for r in reasons)


class TestDomainScoring:
    def test_co_jp_gets_bonus(self):
        score, reasons = score_lead("ABC", "info@abc.co.jp", "https://abc.co.jp", CFG)
        assert any("法人ドメイン" in r for r in reasons)

    def test_jp_domain_gets_bonus(self):
        score, reasons = score_lead("ABC", "info@abc.jp", "https://abc.jp", CFG)
        assert any("法人ドメイン" in r for r in reasons)

    def test_gmail_gets_penalty(self):
        score, reasons = score_lead("ABC", "taro@gmail.com", "https://abc.jp", CFG)
        assert any("個人/フリーメール" in r for r in reasons)

    def test_yahoo_gets_penalty(self):
        score, reasons = score_lead("ABC", "taro@yahoo.co.jp", "https://abc.jp", CFG)
        assert any("個人/フリーメール" in r for r in reasons)


class TestCompanyType:
    def test_kabushiki_gets_bonus(self):
        score, reasons = score_lead("株式会社ABC", "info@abc.co.jp", "https://abc.co.jp", CFG)
        assert any("法人登記" in r for r in reasons)

    def test_yugen_gets_bonus(self):
        score, reasons = score_lead("有限会社ABC", "info@abc.co.jp", "https://abc.co.jp", CFG)
        assert any("法人登記" in r for r in reasons)

    def test_no_company_type_no_bonus(self):
        score, reasons = score_lead("ABCホーム", "info@abc.co.jp", "https://abc.co.jp", CFG)
        assert not any("法人登記" in r for r in reasons)


class TestExcludeKeywords:
    def test_kyujin_in_company_name(self):
        score, reasons = score_lead("株式会社求人ABC", "info@abc.co.jp", "https://abc.co.jp", CFG)
        assert any("除外キーワード" in r for r in reasons)

    def test_ranking_in_company_name(self):
        # Brave 検索がページタイトルを company_name に使う実際の問題
        score, reasons = score_lead("名古屋でおすすめランキング23選", "info@abc.co.jp", "https://abc.co.jp", CFG)
        assert any("除外キーワード" in r for r in reasons)

    def test_exclude_only_fires_once(self):
        # 複数の除外キーワードがあっても-50点は1回だけ
        score, reasons = score_lead("求人転職ABC", "info@abc.co.jp", "https://abc.co.jp", CFG)
        penalty_count = sum(1 for r in reasons if "除外キーワード" in r)
        assert penalty_count == 1


class TestScoreBounds:
    def test_score_never_below_zero(self):
        # 除外キーワード + フリーメール + 全マイナスでもゼロ以上
        score, _ = score_lead("求人転職株式会社", "taro@gmail.com", "https://ranking.jp", CFG)
        assert score >= 0

    def test_score_never_above_100(self):
        # すべてのボーナスが積み重なっても100以下
        score, _ = score_lead("株式会社不動産ABC", "info@abc.co.jp", "https://abc.co.jp/fudosan-chintai", CFG)
        assert score <= 100


class TestFullIcpLead:
    def test_ideal_real_estate_company(self):
        # 目標: 70点以上 → 自動承認（auto_approve_threshold=70）
        score, reasons = score_lead(
            "株式会社山田不動産",
            "info@yamada-fudosan.co.jp",
            "https://yamada-fudosan.co.jp/chintai",
            CFG,
        )
        # +30 (不動産) + +20 (co.jp) + +20 (株式会社) = 70点
        assert score == 70
        assert len(reasons) == 3

    def test_low_quality_lead(self):
        # ランキングサイト経由 + フリーメール → 低スコア
        score, _ = score_lead(
            "名古屋でおすすめランキング23選",
            "info@gmail.com",
            "https://ranking-site.com/fudosan",
            CFG,
        )
        assert score < 50


# ─── 統合テスト: qualify() ────────────────────────────────────

# qualify() 用の設定（auto_approve=70, review=50）
CFG_WITH_THRESHOLDS = {**CFG, "scoring": {**CFG["scoring"],
    "auto_approve_threshold": 70, "review_threshold": 50}}

_LEADS_CSV = """\
company_name,email,url
株式会社山田不動産,info@yamada.co.jp,https://yamada.co.jp/不動産
賃貸ABC,contact@abc.co.jp,https://abc.co.jp
求人求人株式会社,info@gmail.com,https://kyujin.com
"""


class TestQualifyIntegration:
    def test_three_way_split(self, tmp_path):
        # 入力CSVを作成
        input_csv = tmp_path / "leads_raw.csv"
        input_csv.write_text(_LEADS_CSV, encoding="utf-8")

        with patch("qualify_leads.load_config", return_value=CFG_WITH_THRESHOLDS), \
             patch("qualify_leads._GTM_DIR", tmp_path):
            qualify("test_project", str(input_csv))

        approved = list(csv.DictReader(open(tmp_path / "data" / "test_project" / "leads_approved.csv", encoding="utf-8")))
        review = list(csv.DictReader(open(tmp_path / "data" / "test_project" / "leads_review.csv", encoding="utf-8")))
        rejected = list(csv.DictReader(open(tmp_path / "data" / "test_project" / "leads_rejected.csv", encoding="utf-8")))

        # 株式会社山田不動産: +30(不動産) +20(co.jp) +20(株式会社) = 70 → approved
        assert len(approved) == 1
        assert approved[0]["email"] == "info@yamada.co.jp"

        # 賃貸ABC: +30(賃貸) +20(co.jp) = 50 → review（株式会社なし）
        assert len(review) == 1
        assert review[0]["email"] == "contact@abc.co.jp"

        # 求人株式会社: 求人-50 + gmail-20 + 株式会社+20 = 0点 → rejected
        assert len(rejected) == 1
        assert rejected[0]["email"] == "info@gmail.com"

    def test_icp_score_column_added(self, tmp_path):
        input_csv = tmp_path / "leads_raw.csv"
        input_csv.write_text(_LEADS_CSV, encoding="utf-8")

        with patch("qualify_leads.load_config", return_value=CFG_WITH_THRESHOLDS), \
             patch("qualify_leads._GTM_DIR", tmp_path):
            qualify("test_project", str(input_csv))

        approved = list(csv.DictReader(open(tmp_path / "data" / "test_project" / "leads_approved.csv", encoding="utf-8")))
        assert "icp_score" in approved[0]
        assert "score_reasons" in approved[0]
        assert int(approved[0]["icp_score"]) == 70

    def test_three_output_files_always_created(self, tmp_path):
        # 全件 approved でも 3ファイルすべて存在する
        input_csv = tmp_path / "leads_raw.csv"
        input_csv.write_text(
            "company_name,email,url\n"
            "株式会社テスト不動産,info@test.co.jp,https://test.co.jp/不動産\n",
            encoding="utf-8",
        )
        with patch("qualify_leads.load_config", return_value=CFG_WITH_THRESHOLDS), \
             patch("qualify_leads._GTM_DIR", tmp_path):
            qualify("test_project", str(input_csv))

        out_dir = tmp_path / "data" / "test_project"
        assert (out_dir / "leads_approved.csv").exists()
        assert (out_dir / "leads_review.csv").exists()
        assert (out_dir / "leads_rejected.csv").exists()
