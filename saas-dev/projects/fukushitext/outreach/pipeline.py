"""
fukushitext GTMパイプライン（fetch → qualify → generate → ready to send）
  python pipeline.py [--limit 50]
"""
import argparse
import subprocess
import sys
from pathlib import Path

PROJECT = "fukushitext"
_DIR = Path(__file__).parent
_ROOT = _DIR.parent.parent.parent


def run(cmd: list[str]) -> int:
    print(f"\n{'='*60}")
    print(f"実行: {' '.join(cmd)}")
    print("="*60)
    result = subprocess.run(cmd, cwd=str(_ROOT))
    return result.returncode


def main(limit: int = 50):
    steps = [
        [sys.executable, str(_DIR / "fetch_leads.py"), "--limit", str(limit)],
        [sys.executable, str(_ROOT / "shared/gtm/leads/qualify_leads.py"),
         "--project", PROJECT, "--input", str(_DIR / "leads.csv")],
        [sys.executable, str(_ROOT / "shared/gtm/outreach/generate_emails.py"),
         "--project", PROJECT, "--limit", str(limit)],
    ]
    for cmd in steps:
        rc = run(cmd)
        if rc != 0:
            print(f"\nエラー: {cmd[1]} が終了コード {rc} で失敗しました。")
            sys.exit(rc)
    print(f"\n✅ パイプライン完了。send_emails.py --dry-run で内容を確認してください。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    main(args.limit)
