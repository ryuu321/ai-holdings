import os
import sys
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("GEMINI_API_KEY", "dummy-key-for-tests")

from prompt import _quality_ok, _trim_to_limit, generate
from platforms import PLATFORMS


# ── _quality_ok ─────────────────────────────────────────────────────────────

class TestQualityOk:
    def test_clean_japanese_passes(self):
        assert _quality_ok("駅徒歩7分の好立地。南向き2LDKで明るい住まいです。") is True

    def test_star_symbol_fails(self):
        assert _quality_ok("陽当りも★大変良好な2LDK") is False

    def test_comfort_duplication_fails(self):
        assert _quality_ok("快適性と快適さを兼ね備えた物件") is False

    def test_satisfaction_duplication_fails(self):
        assert _quality_ok("満足度が高く満足性のある物件") is False

    def test_hiragana_ascii_mix_fails(self):
        # 平仮名直後に英字は文字化けの兆候
        assert _quality_ok("きA良い物件") is False

    def test_numbers_and_symbols_ok(self):
        # 数字・記号単体はOK
        assert _quality_ok("築8年・58.5㎡・南向き2LDK。駅徒歩7分。") is True

    def test_empty_string_passes(self):
        assert _quality_ok("") is True


# ── _trim_to_limit ───────────────────────────────────────────────────────────

class TestTrimToLimit:
    def test_under_limit_unchanged(self):
        text = "短いテキスト"
        assert _trim_to_limit(text, 40) == text

    def test_exactly_at_limit_unchanged(self):
        text = "あ" * 40
        assert _trim_to_limit(text, 40) == text

    def test_trims_at_sentence_end(self):
        # 40文字を超えて、38文字目に「。」がある場合
        base = "良い物件です。" * 6  # 42文字
        result = _trim_to_limit(base, 40)
        assert len(result) <= 40
        assert result.endswith("。")

    def test_hard_trim_when_no_punctuation(self):
        # 句読点なし → limit文字でハードカット
        text = "あ" * 50
        result = _trim_to_limit(text, 40)
        assert len(result) == 40

    def test_strips_leading_trailing_whitespace(self):
        text = "  良い物件です。  "
        result = _trim_to_limit(text, 40)
        assert not result.startswith(" ")
        assert not result.endswith(" ")

    def test_trim_prefers_exclamation(self):
        # 「！」でも切れるか
        text = "良い物件です！" + "あ" * 40
        result = _trim_to_limit(text, 20)
        assert len(result) <= 20


# ── generate() ───────────────────────────────────────────────────────────────

PLATFORM_INFO = PLATFORMS["SUUMO"]

def _make_mock_response(text: str) -> MagicMock:
    m = MagicMock()
    m.text = text
    return m

def _base_args():
    return dict(
        madori="2LDK",
        eki_toho="7",
        chikunensuu="8",
        muki="南",
        menseki="58.5",
        setsubi=["オートロック", "浴室乾燥機"],
        target="ファミリー",
        platform="SUUMO",
        platform_info=PLATFORM_INFO,
    )


class TestGenerate:
    def test_happy_path_returns_ok(self):
        good_response = (
            "CATCH: 駅7分・築8年リノベ済み南向き2LDK\n"
            "BODY: 駅まで徒歩7分の利便性に優れた住まいです。南向きの明るい室内でご家族の暮らしを豊かに。"
        )
        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.return_value = _make_mock_response(good_response)

            result = generate(**_base_args())

        assert result["ok"] is True
        assert "catch" in result
        assert "body" in result
        assert len(result["catch"]) <= PLATFORM_INFO["catch_max"]
        assert len(result["body"]) <= PLATFORM_INFO["body_max"]

    def test_catch_length_within_platform_limit(self):
        # キャッチが上限ぴったりの場合
        catch = "あ" * PLATFORM_INFO["catch_max"]
        body = "良い物件です。駅まで徒歩7分。南向きで日当たり良好。"
        good_response = f"CATCH: {catch}\nBODY: {body}"

        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.return_value = _make_mock_response(good_response)

            result = generate(**_base_args())

        assert result["ok"] is True
        assert result["catch_len"] <= result["catch_max"]

    def test_malformed_response_retries_then_fails(self):
        # CATCH/BODY フォーマットが全くない → 3回リトライして失敗
        bad_response = "これはフォーマットなしの回答です。"

        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.return_value = _make_mock_response(bad_response)

            result = generate(**_base_args())

        assert result["ok"] is False
        assert "error" in result
        assert mock_client.models.generate_content.call_count == 3

    def test_quality_failure_retries(self):
        # 1回目: 品質NG (★あり) → 2回目: OK
        bad = "CATCH: 陽当り★最高の物件\nBODY: 快適性と快適さに優れた住まいです。"
        good = "CATCH: 駅7分・南向き2LDK\nBODY: 駅まで徒歩7分の好立地。明るい南向き住まいです。"

        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.side_effect = [
                _make_mock_response(bad),
                _make_mock_response(good),
            ]

            result = generate(**_base_args())

        assert result["ok"] is True
        assert mock_client.models.generate_content.call_count == 2

    def test_extra_field_included_in_prompt(self):
        good_response = "CATCH: 駅7分南向き2LDK\nBODY: 駅まで徒歩7分。南向きで明るい。"

        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.return_value = _make_mock_response(good_response)

            generate(**_base_args(), extra="リノベーション済み")

        call_args = mock_client.models.generate_content.call_args
        prompt_text = call_args.kwargs.get("contents") or call_args.args[1]
        assert "リノベーション済み" in prompt_text

    def test_empty_setsubi_handled(self):
        good_response = "CATCH: 駅7分南向き2LDK\nBODY: 駅まで徒歩7分。南向きで明るい住まいです。"

        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.return_value = _make_mock_response(good_response)

            args = _base_args()
            args["setsubi"] = []
            result = generate(**args)

        assert result["ok"] is True


# ── エラーハンドリング ────────────────────────────────────────────────────────

class TestGenerateErrorHandling:
    def test_quota_exceeded_returns_quota_error(self):
        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception(
                "429 RESOURCE_EXHAUSTED: quota exceeded"
            )

            result = generate(**_base_args())

        assert result["ok"] is False
        assert result["error_type"] == "quota"
        assert "上限" in result["error"]

    def test_quota_error_does_not_retry(self):
        # クォータ超過は即座に返す（リトライしても無駄なので）
        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception(
                "429 RESOURCE_EXHAUSTED: quota exceeded"
            )

            generate(**_base_args())

        assert mock_client.models.generate_content.call_count == 1

    def test_network_error_retries_then_returns_api_error(self):
        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.side_effect = ConnectionError("network unreachable")

            result = generate(**_base_args())

        assert result["ok"] is False
        assert result["error_type"] == "api_error"
        assert mock_client.models.generate_content.call_count == 3

    def test_api_error_then_success_recovers(self):
        # 1回目: ネットワークエラー → 2回目: 成功
        good = "CATCH: 駅7分南向き2LDK\nBODY: 駅まで徒歩7分。南向きで明るい住まいです。"

        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.side_effect = [
                ConnectionError("network error"),
                _make_mock_response(good),
            ]

            result = generate(**_base_args())

        assert result["ok"] is True
        assert mock_client.models.generate_content.call_count == 2

    def test_error_result_has_no_catch_or_body(self):
        with patch("prompt._get_client") as mock_get:
            mock_client = MagicMock()
            mock_get.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception("500 internal error")

            result = generate(**_base_args())

        assert "catch" not in result
        assert "body" not in result
