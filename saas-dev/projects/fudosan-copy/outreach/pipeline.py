"""
FudoText コールドメールパイプライン全自動実行
  python pipeline.py            # 収集→qualify→生成→送信
  python pipeline.py --dry-run  # 送信前確認のみ

ステップ:
  1. fetch_mlit_leads.py              (Brave API → leads.csv)
  2. qualify_leads.py                 (ICPスコアリング 70点以上のみ通過)
  3. shared/gtm/outreach/generate_emails.py  (leads_approved.csv → emails_draft.csv)
  4. send_emails.py                   (Gmail SMTP送信 30件/日)

注意: generate_emails.py は必ず shared/gtm 版を使う。
      fudosan-copy/outreach/generate_emails.py は qualify をスキップするため使用禁止。
"""
import argparse
import subprocess
import sys
from pathlib import Path

_DIR = Path(__file__).parent
_GTM = _DIR.parent.parent.parent.parent / "shared" / "gtm"
_ROOT = _DIR.parent.parent.parent.parent


def run(cmd: list[str], label: str) -> bool:
    print(f"\n{'='*50}")
    print(f"[{label}]")
    print(f"{'='*50}")
    result = subprocess.run([sys.executable] + cmd, cwd=str(_ROOT))
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-fetch", action="store_true", help="リード収集をスキップ")
    args = parser.parse_args()

    if not args.skip_fetch:
        ok = run([str(_DIR / "fetch_mlit_leads.py")], "Step 1: リード収集 (Brave API)")
        if not ok:
            print("収集エラー。続行します。")

    leads_csv = str(_DIR / "leads.csv")
    run([str(_GTM / "leads" / "qualify_leads.py"),
         "--project", "fudotext",
         "--input", leads_csv],
        "Step 2: ICPスコアリング")

    gen_args = [str(_GTM / "outreach" / "generate_emails.py"),
                "--project", "fudotext", "--limit", "50"]
    if args.dry_run:
        gen_args.append("--dry-run")
    run(gen_args, "Step 3: メール生成")

    if args.dry_run:
        run([str(_DIR / "send_emails.py"), "--dry-run"],
            "Step 4: 送信プレビュー (dry-run)")
    else:
        run([str(_DIR / "send_emails.py"), "--limit", "29"],
            "Step 4: Gmail SMTP 送信")

    print("\n\nパイプライン完了。")


if __name__ == "__main__":
    main()
