"""
フィードバック自動分析スクリプト。
毎週日曜 GitHub Actions から実行される。
Google Sheets 公開 CSV を読み込み、Gemini で分析し、
domain_knowledge.py を更新して analysis レポートを出力する。
"""

import csv
import io
import os
import re
import sys
import textwrap
import urllib.request
from datetime import datetime, timedelta, timezone


# ──────────────────────────────────────────────────────────────────────────────
# CSV 取得
# ──────────────────────────────────────────────────────────────────────────────

def fetch_csv(url: str) -> str:
    """Google Sheets 公開 CSV を取得して文字列で返す。"""
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# フィードバック解析
# ──────────────────────────────────────────────────────────────────────────────

def parse_feedback(csv_content: str, days: int = 7) -> list[dict]:
    """
    CSV を解析して過去 N 日分の行を返す。
    期待カラム: timestamp, target, platform, rating, regen_count, reasons
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    rows = []
    reader = csv.DictReader(io.StringIO(csv_content))
    for row in reader:
        raw_ts = row.get("timestamp", "").strip()
        if not raw_ts:
            continue
        try:
            # Google Form のタイムスタンプ形式: "2026/05/18 14:30:00"
            dt = datetime.strptime(raw_ts, "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                continue
        if dt >= cutoff:
            rows.append({
                "timestamp": raw_ts,
                "target": row.get("target", "").strip(),
                "platform": row.get("platform", "").strip(),
                "rating": row.get("rating", "").strip(),
                "regen_count": row.get("regen_count", "").strip(),
                "reasons": row.get("reasons", "").strip(),
            })
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# 分析プロンプト構築
# ──────────────────────────────────────────────────────────────────────────────

def build_analysis_prompt(feedback_rows: list[dict]) -> str:
    """Gemini に渡す分析プロンプトを組み立てる。"""
    if not feedback_rows:
        return ""

    total = len(feedback_rows)
    good = sum(1 for r in feedback_rows if r["rating"] == "good")
    bad = total - good
    satisfaction = round(good / total * 100) if total else 0

    reasons_raw = [r["reasons"] for r in feedback_rows if r["reasons"]]
    reasons_text = "\n".join(f"- {r}" for r in reasons_raw) if reasons_raw else "（なし）"

    by_target: dict[str, dict] = {}
    for r in feedback_rows:
        t = r["target"] or "不明"
        by_target.setdefault(t, {"good": 0, "bad": 0})
        if r["rating"] == "good":
            by_target[t]["good"] += 1
        else:
            by_target[t]["bad"] += 1
    target_summary = "\n".join(
        f"  {t}: 👍{v['good']} 👎{v['bad']}" for t, v in by_target.items()
    )

    regen_nums = []
    for r in feedback_rows:
        try:
            regen_nums.append(int(r["regen_count"]))
        except (ValueError, TypeError):
            pass
    avg_regen = round(sum(regen_nums) / len(regen_nums), 1) if regen_nums else "N/A"

    return textwrap.dedent(f"""\
        あなたは不動産物件説明文AIサービス「FudoText」のプロダクト改善アナリストです。
        以下の先週のユーザーフィードバックデータを分析し、
        プロンプトと訴求ポイントの改善案を出力してください。

        【集計】
        - 総フィードバック数: {total}
        - 満足（👍）: {good} ({satisfaction}%)
        - 不満（👎）: {bad}
        - 平均再生成回数: {avg_regen}回

        【ターゲット別満足度】
        {target_summary}

        【不満の理由（自由記述）】
        {reasons_text}

        【分析要件】
        以下の2点について、具体的・実行可能な改善案を出力してください。

        1. TARGET_APPEAL の更新案
           - 不満が多いターゲット層の訴求ポイントを強化する
           - 現在のキー: ファミリー / カップル・DINKS / 単身者（社会人）/ 単身者（学生）/ シニア / 投資家
           - 変更する場合のみ出力。形式: `キー名: 新しい訴求ポイント文字列`

        2. CONVERSION_TIPS の追記・修正案
           - 不満理由から読み取れる表現パターンの弱点を補う
           - 追加するルールのみ箇条書きで出力

        【出力フォーマット（このまま返す）】
        TARGET_APPEAL_UPDATES:
        （変更するキーと値を1行ずつ。なければ「なし」）

        CONVERSION_TIPS_ADDITIONS:
        （追加するルールを箇条書き。なければ「なし」）

        SUMMARY:
        （改善の根拠と期待効果を100文字以内で）
    """)


# ──────────────────────────────────────────────────────────────────────────────
# domain_knowledge.py への適用
# ──────────────────────────────────────────────────────────────────────────────

def _bump_version(version: str) -> str:
    """'v1.1' → 'v1.2' のようにマイナーバージョンをインクリメント。"""
    m = re.match(r"v(\d+)\.(\d+)", version)
    if not m:
        return version
    return f"v{m.group(1)}.{int(m.group(2)) + 1}"


def apply_improvements(analysis_text: str, domain_knowledge_path: str) -> bool:
    """
    Gemini の分析結果を domain_knowledge.py に反映する。
    変更があった場合 True を返す。
    """
    with open(domain_knowledge_path, encoding="utf-8") as f:
        source = f.read()

    # TARGET_APPEAL_UPDATES を解析
    ta_match = re.search(
        r"TARGET_APPEAL_UPDATES:\s*\n(.*?)(?=\n\n|\nCONVERSION_TIPS_ADDITIONS:)",
        analysis_text,
        re.DOTALL,
    )
    ta_lines = ta_match.group(1).strip() if ta_match else ""

    # CONVERSION_TIPS_ADDITIONS を解析
    ct_match = re.search(
        r"CONVERSION_TIPS_ADDITIONS:\s*\n(.*?)(?=\n\nSUMMARY:|\Z)",
        analysis_text,
        re.DOTALL,
    )
    ct_lines = ct_match.group(1).strip() if ct_match else ""

    changed = False

    # TARGET_APPEAL 更新
    if ta_lines and ta_lines != "なし":
        for line in ta_lines.splitlines():
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if not key or not value:
                continue
            # "キー":       "旧値", を "キー":       "新値", に置換
            old_pattern = rf'("{re.escape(key)}"\s*:\s*)"[^"]*"'
            new_line = rf'\1"{value}"'
            new_source = re.sub(old_pattern, new_line, source)
            if new_source != source:
                source = new_source
                changed = True

    # CONVERSION_TIPS 追記
    if ct_lines and ct_lines != "なし":
        new_tips = "\n".join(
            f"- {l.lstrip('- ').strip()}"
            for l in ct_lines.splitlines()
            if l.strip() and not l.strip().startswith("#")
        )
        # CONVERSION_TIPS 末尾の """ の直前に追記
        new_source = source.replace(
            '- 禁止: 根拠のない断言（「絶対に〇〇」「必ず〇〇」）\n"""',
            f'- 禁止: 根拠のない断言（「絶対に〇〇」「必ず〇〇」）\n{new_tips}\n"""',
        )
        if new_source != source:
            source = new_source
            changed = True

    # PROMPT_VERSION をバンプ
    if changed:
        version_match = re.search(r'PROMPT_VERSION\s*=\s*"(v[\d.]+)"', source)
        if version_match:
            old_ver = version_match.group(1)
            new_ver = _bump_version(old_ver)
            source = source.replace(
                f'PROMPT_VERSION = "{old_ver}"',
                f'PROMPT_VERSION = "{new_ver}"',
            )

    if changed:
        with open(domain_knowledge_path, "w", encoding="utf-8") as f:
            f.write(source)

    return changed


# ──────────────────────────────────────────────────────────────────────────────
# レポート保存
# ──────────────────────────────────────────────────────────────────────────────

def save_analysis(
    analysis_text: str,
    stats: dict,
    output_path: str,
) -> None:
    """分析結果を Markdown レポートとして保存する。"""
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    content = textwrap.dedent(f"""\
        # フィードバック分析レポート — {date_str}

        ## 集計
        - 総フィードバック数: {stats.get('total', 0)}
        - 満足率: {stats.get('satisfaction', 0)}%
        - 平均再生成回数: {stats.get('avg_regen', 'N/A')}

        ## Gemini 分析結果

        {analysis_text}
    """)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


# ──────────────────────────────────────────────────────────────────────────────
# エントリポイント
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    csv_url = os.environ.get("FEEDBACK_SHEET_CSV_URL", "")
    gemini_api_key = os.environ.get("GEMINI_API_KEY", "")

    if not csv_url:
        print("ERROR: FEEDBACK_SHEET_CSV_URL が設定されていません", file=sys.stderr)
        sys.exit(1)
    if not gemini_api_key:
        print("ERROR: GEMINI_API_KEY が設定されていません", file=sys.stderr)
        sys.exit(1)

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    domain_knowledge_path = os.path.join(project_root, "domain_knowledge.py")
    report_dir = os.path.join(project_root, "feedback_reports")
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    report_path = os.path.join(report_dir, f"{date_str}.md")

    print("フィードバック CSV を取得中...")
    try:
        csv_content = fetch_csv(csv_url)
    except Exception as e:
        print(f"ERROR: CSV 取得失敗: {e}", file=sys.stderr)
        sys.exit(1)

    rows = parse_feedback(csv_content, days=7)
    print(f"過去7日のフィードバック: {len(rows)} 件")

    if not rows:
        print("フィードバックなし。スキップします。")
        sys.exit(0)

    total = len(rows)
    good = sum(1 for r in rows if r["rating"] == "good")
    satisfaction = round(good / total * 100) if total else 0
    regen_nums = []
    for r in rows:
        try:
            regen_nums.append(int(r["regen_count"]))
        except (ValueError, TypeError):
            pass
    avg_regen = round(sum(regen_nums) / len(regen_nums), 1) if regen_nums else "N/A"
    stats = {"total": total, "satisfaction": satisfaction, "avg_regen": avg_regen}

    prompt = build_analysis_prompt(rows)

    print("Gemini で分析中...")
    from google import genai  # ランタイム import（テスト時は不要）
    client = genai.Client(api_key=gemini_api_key)
    response = client.models.generate_content(
        model="gemini-flash-latest",
        contents=prompt,
    )
    analysis_text = response.text.strip()

    print("domain_knowledge.py に改善を適用中...")
    changed = apply_improvements(analysis_text, domain_knowledge_path)
    print(f"変更あり: {changed}")

    print(f"レポートを保存中: {report_path}")
    save_analysis(analysis_text, stats, report_path)

    if changed:
        print("CHANGED=true")
    else:
        print("CHANGED=false")


if __name__ == "__main__":
    main()
