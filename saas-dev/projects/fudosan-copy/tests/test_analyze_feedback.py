import os
import sys
import textwrap
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

from scripts.analyze_feedback import (
    _bump_version,
    apply_improvements,
    build_analysis_prompt,
    parse_feedback,
    save_analysis,
)


# ──────────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────────

def _ts(days_ago: int = 0) -> str:
    dt = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y/%m/%d %H:%M:%S")


def _make_csv(*rows: dict) -> str:
    header = "timestamp,target,platform,rating,regen_count,reasons"
    lines = [header]
    for r in rows:
        lines.append(
            f"{r.get('timestamp', _ts())},{r.get('target', 'ファミリー')},"
            f"{r.get('platform', 'SUUMO')},{r.get('rating', 'good')},"
            f"{r.get('regen_count', '1')},{r.get('reasons', '')}"
        )
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# _bump_version
# ──────────────────────────────────────────────────────────────────────────────

class TestBumpVersion:
    def test_increments_minor(self):
        assert _bump_version("v1.1") == "v1.2"

    def test_increments_from_nine(self):
        assert _bump_version("v1.9") == "v1.10"

    def test_major_unchanged(self):
        assert _bump_version("v2.3") == "v2.4"

    def test_invalid_format_unchanged(self):
        assert _bump_version("invalid") == "invalid"

    def test_v1_0(self):
        assert _bump_version("v1.0") == "v1.1"


# ──────────────────────────────────────────────────────────────────────────────
# parse_feedback
# ──────────────────────────────────────────────────────────────────────────────

class TestParseFeedback:
    def test_returns_recent_rows(self):
        csv_content = _make_csv(
            {"timestamp": _ts(0), "rating": "good"},
            {"timestamp": _ts(3), "rating": "bad"},
        )
        rows = parse_feedback(csv_content, days=7)
        assert len(rows) == 2

    def test_excludes_old_rows(self):
        csv_content = _make_csv(
            {"timestamp": _ts(0), "rating": "good"},
            {"timestamp": _ts(10), "rating": "bad"},
        )
        rows = parse_feedback(csv_content, days=7)
        assert len(rows) == 1
        assert rows[0]["rating"] == "good"

    def test_empty_csv_returns_empty(self):
        rows = parse_feedback("timestamp,target,platform,rating,regen_count,reasons", days=7)
        assert rows == []

    def test_skips_rows_without_timestamp(self):
        csv_content = "timestamp,target,platform,rating,regen_count,reasons\n,ファミリー,SUUMO,good,1,"
        rows = parse_feedback(csv_content, days=7)
        assert rows == []

    def test_fields_mapped_correctly(self):
        csv_content = _make_csv(
            {
                "timestamp": _ts(1),
                "target": "シニア",
                "platform": "HOMES",
                "rating": "bad",
                "regen_count": "3",
                "reasons": "文章が短すぎる",
            }
        )
        rows = parse_feedback(csv_content, days=7)
        assert len(rows) == 1
        r = rows[0]
        assert r["target"] == "シニア"
        assert r["platform"] == "HOMES"
        assert r["rating"] == "bad"
        assert r["regen_count"] == "3"
        assert r["reasons"] == "文章が短すぎる"

    def test_boundary_exactly_n_days_ago_included(self):
        # cutoff = now - 7 days. A row at exactly 7 days ago should be included
        # (>= cutoff, not >).
        dt = datetime.now(tz=timezone.utc) - timedelta(days=7, seconds=-1)
        ts = dt.strftime("%Y/%m/%d %H:%M:%S")
        csv_content = _make_csv({"timestamp": ts})
        rows = parse_feedback(csv_content, days=7)
        assert len(rows) == 1


# ──────────────────────────────────────────────────────────────────────────────
# build_analysis_prompt
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildAnalysisPrompt:
    def test_returns_empty_for_no_rows(self):
        assert build_analysis_prompt([]) == ""

    def test_contains_output_format(self):
        rows = [{"target": "ファミリー", "platform": "SUUMO", "rating": "good",
                 "regen_count": "1", "reasons": ""}]
        prompt = build_analysis_prompt(rows)
        assert "TARGET_APPEAL_UPDATES:" in prompt
        assert "CONVERSION_TIPS_ADDITIONS:" in prompt
        assert "SUMMARY:" in prompt

    def test_satisfaction_rate_calculated(self):
        rows = [
            {"target": "ファミリー", "platform": "SUUMO", "rating": "good", "regen_count": "1", "reasons": ""},
            {"target": "シニア", "platform": "SUUMO", "rating": "bad", "regen_count": "2", "reasons": "短い"},
        ]
        prompt = build_analysis_prompt(rows)
        assert "50%" in prompt

    def test_reasons_included(self):
        rows = [
            {"target": "単身者（社会人）", "platform": "SUUMO", "rating": "bad",
             "regen_count": "3", "reasons": "補足情報が反映されていない"},
        ]
        prompt = build_analysis_prompt(rows)
        assert "補足情報が反映されていない" in prompt

    def test_all_good_shows_100_percent(self):
        rows = [
            {"target": "ファミリー", "platform": "SUUMO", "rating": "good", "regen_count": "1", "reasons": ""}
            for _ in range(5)
        ]
        prompt = build_analysis_prompt(rows)
        assert "100%" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# apply_improvements
# ──────────────────────────────────────────────────────────────────────────────

DOMAIN_KNOWLEDGE_TEMPLATE = '''\
"""
不動産物件説明文に関するドメイン知識。
"""

PROMPT_VERSION = "v1.1"

TARGET_APPEAL = {{
    "ファミリー":       "{family_appeal}",
    "カップル・DINKS":  "おしゃれさ・二人の時間・利便性・キッチンや浴室のグレード感",
    "単身者（社会人）": "通勤利便性・セキュリティ・収納・帰ってからくつろげる空間",
    "単身者（学生）":   "駅近・コスパ・シンプルな生活のしやすさ",
    "シニア":           "バリアフリー・静かさ・買い物のしやすさ・管理の楽さ",
    "投資家":           "利回り・管理費・エリアの賃貸需要・表面利回りの根拠",
}}

CONVERSION_TIPS = """
【成約率を上げる表現の原則】
- 数字を使う: 「広い」より「58㎡」「収納3か所」「徒歩7分」
- 禁止: 根拠のない断言（「絶対に〇〇」「必ず〇〇」）
"""
'''


def _write_domain(tmp_path, family_appeal="広さ・収納・学区"):
    path = tmp_path / "domain_knowledge.py"
    path.write_text(
        DOMAIN_KNOWLEDGE_TEMPLATE.format(family_appeal=family_appeal),
        encoding="utf-8",
    )
    return str(path)


class TestApplyImprovements:
    def test_no_changes_returns_false(self, tmp_path):
        path = _write_domain(tmp_path)
        analysis = "TARGET_APPEAL_UPDATES:\nなし\n\nCONVERSION_TIPS_ADDITIONS:\nなし\n\nSUMMARY:\nなし"
        changed = apply_improvements(analysis, path)
        assert changed is False

    def test_target_appeal_updated(self, tmp_path):
        path = _write_domain(tmp_path)
        analysis = textwrap.dedent("""\
            TARGET_APPEAL_UPDATES:
            ファミリー: 広さ・学区・公園・防犯カメラ

            CONVERSION_TIPS_ADDITIONS:
            なし

            SUMMARY:
            ファミリー向け安全訴求を強化
        """)
        changed = apply_improvements(analysis, path)
        assert changed is True
        content = open(path, encoding="utf-8").read()
        assert "広さ・学区・公園・防犯カメラ" in content

    def test_version_bumped_when_changed(self, tmp_path):
        path = _write_domain(tmp_path)
        analysis = textwrap.dedent("""\
            TARGET_APPEAL_UPDATES:
            ファミリー: 新しい訴求ポイント

            CONVERSION_TIPS_ADDITIONS:
            なし

            SUMMARY:
            テスト
        """)
        apply_improvements(analysis, path)
        content = open(path, encoding="utf-8").read()
        assert 'PROMPT_VERSION = "v1.2"' in content

    def test_version_not_bumped_when_no_change(self, tmp_path):
        path = _write_domain(tmp_path)
        analysis = "TARGET_APPEAL_UPDATES:\nなし\n\nCONVERSION_TIPS_ADDITIONS:\nなし\n\nSUMMARY:\nなし"
        apply_improvements(analysis, path)
        content = open(path, encoding="utf-8").read()
        assert 'PROMPT_VERSION = "v1.1"' in content

    def test_conversion_tips_appended(self, tmp_path):
        path = _write_domain(tmp_path)
        analysis = textwrap.dedent("""\
            TARGET_APPEAL_UPDATES:
            なし

            CONVERSION_TIPS_ADDITIONS:
            - 写真の枚数を説明文に書く（「写真20枚掲載」）

            SUMMARY:
            写真訴求の強化
        """)
        changed = apply_improvements(analysis, path)
        assert changed is True
        content = open(path, encoding="utf-8").read()
        assert "写真の枚数を説明文に書く" in content

    def test_unknown_target_key_ignored(self, tmp_path):
        path = _write_domain(tmp_path)
        original = open(path, encoding="utf-8").read()
        analysis = textwrap.dedent("""\
            TARGET_APPEAL_UPDATES:
             存在しないキー: 何かの値

            CONVERSION_TIPS_ADDITIONS:
            なし

            SUMMARY:
            テスト
        """)
        changed = apply_improvements(analysis, path)
        assert changed is False
        content = open(path, encoding="utf-8").read()
        assert content == original


# ──────────────────────────────────────────────────────────────────────────────
# save_analysis
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveAnalysis:
    def test_creates_file(self, tmp_path):
        output_path = str(tmp_path / "reports" / "2026-05-19.md")
        save_analysis("分析テキスト", {"total": 5, "satisfaction": 80, "avg_regen": 1.5}, output_path)
        assert os.path.exists(output_path)

    def test_file_contains_stats(self, tmp_path):
        output_path = str(tmp_path / "reports" / "2026-05-19.md")
        save_analysis("分析テキスト", {"total": 10, "satisfaction": 60, "avg_regen": 2.0}, output_path)
        content = open(output_path, encoding="utf-8").read()
        assert "10" in content
        assert "60%" in content

    def test_file_contains_analysis(self, tmp_path):
        output_path = str(tmp_path / "2026-05-19.md")
        save_analysis("TARGET_APPEAL_UPDATES:\nなし", {"total": 1, "satisfaction": 100, "avg_regen": 1}, output_path)
        content = open(output_path, encoding="utf-8").read()
        assert "TARGET_APPEAL_UPDATES" in content
