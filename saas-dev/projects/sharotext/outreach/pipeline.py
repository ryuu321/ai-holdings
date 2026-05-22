"""
SharoText アウトリーチ パイプライン（1コマンドで全工程を実行）

  python pipeline.py              # フルパイプライン（fetch→qualify→generate→確認→send）
  python pipeline.py --no-send    # 送信なし（ドラフト生成まで）
  python pipeline.py --dry-run    # 全工程をドライラン（実際には送信しない）
  python pipeline.py --fetch-only # リード収集のみ
  python pipeline.py --force      # 会社名確認をスキップ（GitHub Actions用）
"""
import argparse
import csv
import subprocess
import sys
from pathlib import Path

_DIR = Path(__file__).parent
_ROOT = _DIR.parent.parent.parent.parent.parent  # ai-holdings/

_FETCH = _DIR / "fetch_leads.py"
_QUALIFY = _ROOT / "shared" / "gtm" / "leads" / "qualify_leads.py"
_GENERATE = _ROOT / "shared" / "gtm" / "outreach" / "generate_emails.py"
_SEND = _DIR / "send_emails.py"

PROJECT = "sharotext"
LEADS_CSV = _DIR / "leads.csv"


def run(cmd: list[str], label: str) -> bool:
    print(f"\n{'='*60}")
    print(f"[{label}]")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=str(_ROOT))
    if result.returncode != 0:
        print(f"ERROR: {label} が失敗しました（終了コード {result.returncode}）")
        return False
    return True


def _review_draft(draft_file: Path, send_limit: int, force: bool) -> bool:
    """draft CSVの会社名を表示してユーザー確認を取る。force=TrueはGitHub Actions用。"""
    if not draft_file.exists():
        print("draft CSVが見つかりません。")
        return False

    with open(draft_file, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("status") == "draft"]

    targets = rows[:send_limit]
    if not targets:
        print("送信対象のdraftがありません。")
        return False

    print(f"\n{'='*60}")
    print(f"[STEP 3.5: 送信前 会社名確認] {len(targets)}件")
    print(f"{'='*60}")
    for i, row in enumerate(targets, 1):
        personalized = "AI" if row.get("personalized") == "True" else "FB"
        print(f"  {i:2}. [{personalized}] {row['company_name'][:35]} | {row['email']}")

    if force:
        print("\n--force: 確認スキップして送信します。")
        return True

    print("\n上記の企業名・メールアドレスを確認してください。")
    ans = input("送信しますか？ [y/N]: ").strip().lower()
    return ans == "y"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-send", action="store_true", help="ドラフト生成まで（送信しない）")
    parser.add_argument("--dry-run", action="store_true", help="全工程ドライラン")
    parser.add_argument("--fetch-only", action="store_true", help="リード収集のみ")
    parser.add_argument("--fetch-limit", type=int, default=100, help="1回の収集上限（デフォルト100）")
    parser.add_argument("--send-limit", type=int, default=30, help="1回の送信上限（デフォルト30）")
    parser.add_argument("--force", action="store_true", help="会社名確認をスキップ（GitHub Actions用）")
    args = parser.parse_args()

    py = sys.executable

    # Step 1: リード収集
    ok = run(
        [py, str(_FETCH), "--limit", str(args.fetch_limit)],
        "STEP 1: リード収集 (fetch_leads.py)"
    )
    if not ok:
        return
    if args.fetch_only:
        print("\nfetch-only モード: リード収集のみ完了しました。")
        return

    # Step 2: ICP スコアリング（leads.csv → leads_approved.csv）
    ok = run(
        [py, str(_QUALIFY), "--project", PROJECT, "--input", str(LEADS_CSV)],
        "STEP 2: ICPスコアリング (qualify_leads.py)"
    )
    if not ok:
        return

    # Step 3: メール草稿生成
    generate_args = [py, str(_GENERATE), "--project", PROJECT]
    if args.dry_run:
        generate_args.append("--dry-run")
    ok = run(generate_args, "STEP 3: メール草稿生成 (generate_emails.py)")
    if not ok:
        return

    if args.no_send or args.dry_run:
        print("\n--no-send / --dry-run モード: 送信をスキップしました。")
        print("送信する場合: python pipeline.py --force  または  python send_emails.py")
        return

    # Step 3.5: 会社名確認（強制ゲート）
    project_dir_name = {"sharotext": "sharotext"}.get(PROJECT, PROJECT)
    draft_file = _ROOT / "saas-dev" / "projects" / project_dir_name / "outreach" / "emails_draft.csv"
    if not _review_draft(draft_file, args.send_limit, args.force):
        print("\n送信をキャンセルしました。")
        return

    # Step 4: 送信
    ok = run(
        [py, str(_SEND), "--limit", str(args.send_limit)],
        "STEP 4: メール送信 (send_emails.py)"
    )
    if not ok:
        return

    print("\n全工程完了。")


if __name__ == "__main__":
    main()
