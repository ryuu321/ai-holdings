"""
共通 フィードバック分析スクリプト。
Google フォーム公開 CSV を取得し Gemini で分析してレポートを保存する。

Usage:
  python analyze_feedback.py --project fudotext
  python analyze_feedback.py --project sharotext --days 14
"""
import argparse
import csv
import io
import json
import os
import sys
import textwrap
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CFG_DIR = _ROOT / "shared" / "gtm" / "config"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_ROOT / ".env")
except ImportError:
    pass

MODEL = "gemini-3.1-flash-lite"
MAX_TOKENS = 2000


def _load_config(project: str) -> dict:
    path = _CFG_DIR / f"{project}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_csv(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


def parse_feedback(csv_content: str, days: int = 7) -> list[dict]:
    """
    過去 N 日分の行を返す。
    期待カラム: timestamp, rating, regen_count, reasons (+ 製品ごとの追加カラム)
    """
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    rows = []
    reader = csv.DictReader(io.StringIO(csv_content))
    for row in reader:
        raw_ts = row.get("timestamp", "").strip()
        if not raw_ts:
            continue
        try:
            dt = datetime.strptime(raw_ts, "%Y/%m/%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                dt = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                continue
        if dt >= cutoff:
            rows.append({
                "timestamp": raw_ts,
                "rating": row.get("rating", "").strip(),
                "regen_count": row.get("regen_count", "").strip(),
                "reasons": row.get("reasons", "").strip(),
                "extra": {k: v for k, v in row.items()
                          if k not in ("timestamp", "rating", "regen_count", "reasons")},
            })
    return rows


def build_prompt(rows: list[dict], product_name: str, extra_context: str = "") -> str:
    total = len(rows)
    good = sum(1 for r in rows if r["rating"] == "good")
    satisfaction = round(good / total * 100) if total else 0
    bad = total - good

    reasons_text = "\n".join(
        f"- {r['reasons']}" for r in rows if r["reasons"]
    ) or "（なし）"

    regen_nums = []
    for r in rows:
        try:
            regen_nums.append(int(r["regen_count"]))
        except (ValueError, TypeError):
            pass
    avg_regen = round(sum(regen_nums) / len(regen_nums), 1) if regen_nums else "N/A"

    extra_section = f"\n【製品固有情報】\n{extra_context}\n" if extra_context else ""

    return textwrap.dedent(f"""\
        あなたは「{product_name}」のプロダクト改善アナリストです。
        以下の先週のユーザーフィードバックデータを分析し、
        AIプロンプトと訴求ポイントの改善案を出力してください。
        {extra_section}
        【集計】
        - 総フィードバック数: {total}
        - 満足（good）: {good} ({satisfaction}%)
        - 不満（bad）: {bad}
        - 平均再生成回数: {avg_regen}回

        【不満の理由（自由記述）】
        {reasons_text}

        【分析要件】
        以下の2点について、具体的・実行可能な改善案を出力してください。

        1. プロンプト改善案
           - 不満が多い点を補うプロンプト修正の方向性を示す
           - 変更箇所が明確になるよう「現状→改善案」形式で記述

        2. 訴求ポイント改善案
           - コールドメール・LP の訴求で強化すべきポイント
           - 追加するメッセージのみ箇条書きで出力

        【出力フォーマット（このまま返す）】
        PROMPT_IMPROVEMENTS:
        （改善案を1行ずつ。なければ「なし」）

        APPEAL_ADDITIONS:
        （追加する訴求ポイントを箇条書き。なければ「なし」）

        SUMMARY:
        （改善の根拠と期待効果を100文字以内で）
    """)


def call_gemini(prompt: str, api_key: str) -> str:
    import urllib.error
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": MAX_TOKENS, "temperature": 0.3},
    }).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def save_report(analysis: str, stats: dict, report_path: Path) -> None:
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    content = textwrap.dedent(f"""\
        # フィードバック分析レポート — {date_str}

        ## 集計
        - 総フィードバック数: {stats.get('total', 0)}
        - 満足率: {stats.get('satisfaction', 0)}%
        - 平均再生成回数: {stats.get('avg_regen', 'N/A')}

        ## Gemini 分析結果

        {analysis}
    """)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")
    print(f"レポート保存: {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    cfg = _load_config(args.project)
    product_name = cfg["product_name"]
    csv_env_key = cfg.get("feedback_csv_env", f"{args.project.upper()}_FEEDBACK_CSV_URL")
    report_dir = _ROOT / cfg.get("feedback_report_dir", f"saas-dev/projects/{args.project}/feedback_reports")
    extra_context = cfg.get("feedback_prompt_context", "")

    csv_url = os.environ.get(csv_env_key, "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")

    if not csv_url:
        print(f"ERROR: {csv_env_key} が設定されていません", file=sys.stderr)
        sys.exit(1)
    if not gemini_key:
        print("ERROR: GEMINI_API_KEY が設定されていません", file=sys.stderr)
        sys.exit(1)

    print(f"[{product_name}] フィードバック CSV を取得中...")
    try:
        csv_content = fetch_csv(csv_url)
    except Exception as e:
        print(f"ERROR: CSV 取得失敗: {e}", file=sys.stderr)
        sys.exit(1)

    rows = parse_feedback(csv_content, days=args.days)
    print(f"過去{args.days}日のフィードバック: {len(rows)}件")

    if not rows:
        print("フィードバックなし。スキップします。")
        sys.exit(0)

    total = len(rows)
    good = sum(1 for r in rows if r["rating"] == "good")
    satisfaction = round(good / total * 100) if total else 0
    regen_nums = [int(r["regen_count"]) for r in rows
                  if r["regen_count"].isdigit()]
    avg_regen = round(sum(regen_nums) / len(regen_nums), 1) if regen_nums else "N/A"
    stats = {"total": total, "satisfaction": satisfaction, "avg_regen": avg_regen}

    print("Gemini で分析中...")
    prompt = build_prompt(rows, product_name, extra_context)
    try:
        analysis = call_gemini(prompt, gemini_key)
    except Exception as e:
        print(f"ERROR: Gemini 呼び出し失敗: {e}", file=sys.stderr)
        sys.exit(1)

    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    report_path = report_dir / f"{date_str}.md"
    save_report(analysis, stats, report_path)

    print("DONE")
    print(f"満足率: {satisfaction}% ({good}/{total})")


if __name__ == "__main__":
    main()
