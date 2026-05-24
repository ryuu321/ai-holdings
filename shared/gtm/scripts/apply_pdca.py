"""
フィードバックレポートの PROMPT_IMPROVEMENTS を読んで gen.py の _PROMPTS を自動改善するスクリプト。

Usage:
  python shared/gtm/scripts/apply_pdca.py --project sharotext

動作:
  1. saas-dev/projects/{project}/feedback_reports/ の最新レポートを読む
  2. PROMPT_IMPROVEMENTS セクションを抽出
  3. 「なし」なら何もしない
  4. 改善案がある場合: Gemini で gen.py の _PROMPTS / PROMPT_TEMPLATES を改善案を反映して書き直す
  5. fudotext リポジトリの gen.py を更新する
     - ローカル: C:/Users/ryuuM/fudotext/saas-dev/projects/{dir}/gen.py を直接更新
     - GitHub Actions: FUDOTEXT_PAT を使って clone → update → push
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CFG_DIR = _ROOT / "shared" / "gtm" / "config"

# fudotext リポジトリのルート（ローカル実行時）
_FUDOTEXT_LOCAL = Path("C:/Users/ryuuM/fudotext")

# config_project -> fudotext_dir マッピング
PROJECT_DIR_MAP = {
    "aftertext": "aftertext",
    "caretext": "caretext",
    "churntext": "churntext",
    "cmtext": "cmtext",
    "daytext": "daytext",
    "denkitext": "denkitext",
    "fudotext": "fudosan-copy",
    "gyotext": "gyotext",
    "iintext": "iintext",
    "jukutext": "jukutext",
    "kanritext": "kanritext",
    "kentext": "kensetsu",
    "pharmtext": "pharmtext",
    "sharotext": "sharotext",
    "shoshitext": "shoshitext",
    "taxtext": "taxtext",
    "tokutext": "tokutext",
    "tostext": "tostext",
}

GEMINI_MODEL = "gemini-2.5-flash"

# 危険なパターン（Gemini生成コードに含まれる場合はスキップ）
_DANGEROUS_PATTERNS = [
    r"\bos\.system\b",
    r"\bsubprocess\b",
    r"\bexec\b\s*\(",
    r"\beval\b\s*\(",
    r"\b__import__\b",
    r"\bimport\s+os\b",
    r"\bimport\s+sys\b",
    r"\bopen\s*\(",
    r"\brm\s+-rf\b",
    r"\bdel\s+/",
]


# .envロード
_env_file = _ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())


def load_config(project: str) -> dict:
    path = _CFG_DIR / f"{project}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_latest_report(report_dir: Path) -> Path | None:
    """feedback_reports/ の最新 .md ファイルを返す。"""
    reports = sorted(report_dir.glob("*.md"), reverse=True)
    return reports[0] if reports else None


def extract_prompt_improvements(report_content: str) -> str | None:
    """
    レポートから PROMPT_IMPROVEMENTS セクションを抽出する。
    「なし」の場合は None を返す。
    """
    match = re.search(
        r"PROMPT_IMPROVEMENTS:\s*\n(.*?)(?=\n[A-Z_]+:|$)",
        report_content,
        re.DOTALL,
    )
    if not match:
        return None
    content = match.group(1).strip()
    if content.lower() in ("なし", "none", ""):
        return None
    return content


def call_gemini(prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません")
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 8192, "temperature": 0.2},
    }).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Gemini API エラー ({e.code}): {body}") from None


def build_pdca_prompt(gen_py_content: str, improvements: str, product_name: str) -> str:
    return f"""あなたは「{product_name}」のAIプロダクト開発者です。
以下のプロンプト改善案を、gen.py の _PROMPTS 変数（または PROMPT_TEMPLATE 等のプロンプト文字列）に反映してください。

【プロンプト改善案】
{improvements}

【現在の gen.py】
```python
{gen_py_content}
```

【出力規則】
1. gen.py 全体を書き直したコードのみを出力する（コード以外の説明は不要）
2. プロンプト文字列（_PROMPTS / PROMPT_TEMPLATE / SYSTEM_PROMPT 等）の内容のみを改善案に基づいて変更する
3. 関数・クラス・インポート構造は変更しない
4. 改善案に無関係な箇所は一切変更しない
5. 出力は ```python ... ``` のコードブロックで囲む
6. os.system / subprocess / exec / eval / __import__ / open() などの危険な操作を含めない
"""


def is_safe_code(code: str) -> bool:
    """生成されたコードに危険なパターンがないか確認する。"""
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, code):
            print(f"  [SECURITY] 危険なパターン検出: {pattern}")
            return False
    return True


def extract_code_from_response(response: str) -> str | None:
    """Gemini レスポンスからコードブロックを抽出する。"""
    match = re.search(r"```python\n(.*?)```", response, re.DOTALL)
    if match:
        return match.group(1)
    # コードブロックなしで返ってきた場合
    if "def " in response or "import " in response:
        return response
    return None


def apply_to_local_fudotext(project: str, gen_py_path: Path, new_content: str, old_content: str) -> bool:
    """ローカルの fudotext リポジトリに直接書き込む。"""
    # バックアップ
    backup_path = gen_py_path.with_suffix(".py.bak")
    backup_path.write_text(old_content, encoding="utf-8")
    print(f"  バックアップ: {backup_path}")

    # 変更前後の diff をログ出力
    diff = list(difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile="gen.py (before)",
        tofile="gen.py (after)",
        n=3,
    ))
    if diff:
        print("  diff:")
        for line in diff[:50]:  # 最大50行
            print("   " + line.rstrip())
        if len(diff) > 50:
            print(f"  ... (+{len(diff)-50} 行)")

    gen_py_path.write_text(new_content, encoding="utf-8")
    print(f"  gen.py 更新: {gen_py_path}")
    return True


def apply_via_git_clone(project: str, fudo_dir: str, new_gen_py: str, old_gen_py: str) -> bool:
    """
    GitHub Actions 環境での更新。
    FUDOTEXT_PAT を使って fudotext リポジトリを clone → gen.py を更新 → push する。
    """
    pat = os.environ.get("FUDOTEXT_PAT", "")
    if not pat:
        print("  [WARN] FUDOTEXT_PAT が未設定。git clone をスキップします。")
        return False

    repo_url = f"https://{pat}@github.com/ryuu321/fudotext.git"
    date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    with tempfile.TemporaryDirectory() as tmpdir:
        # clone
        print("  fudotext リポジトリを clone 中...")
        result = subprocess.run(
            ["git", "clone", "--depth=1", repo_url, tmpdir],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  [ERROR] git clone 失敗: {result.stderr}")
            return False

        gen_path = Path(tmpdir) / "saas-dev" / "projects" / fudo_dir / "gen.py"
        if not gen_path.exists():
            print(f"  [ERROR] gen.py が見つかりません: {gen_path}")
            return False

        # バックアップ
        backup_path = gen_path.with_suffix(".py.bak")
        backup_path.write_text(old_gen_py, encoding="utf-8")

        # diff ログ
        diff = list(difflib.unified_diff(
            old_gen_py.splitlines(keepends=True),
            new_gen_py.splitlines(keepends=True),
            fromfile="gen.py (before)",
            tofile="gen.py (after)",
            n=3,
        ))
        if diff:
            print("  diff:")
            for line in diff[:50]:
                print("   " + line.rstrip())

        # 更新
        gen_path.write_text(new_gen_py, encoding="utf-8")

        # git commit & push
        subprocess.run(["git", "config", "user.email", "actions@github.com"], cwd=tmpdir)
        subprocess.run(["git", "config", "user.name", "Auto Bot"], cwd=tmpdir)
        subprocess.run(["git", "add", str(gen_path)], cwd=tmpdir)

        check = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            cwd=tmpdir, capture_output=True
        )
        if check.returncode == 0:
            print("  変更なし（git diff empty）")
            return False

        commit_msg = f"{project}: PDCA gen.py 自動改善 {date_str} [skip ci]"
        subprocess.run(["git", "commit", "-m", commit_msg], cwd=tmpdir)
        result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=tmpdir, capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  [ERROR] git push 失敗: {result.stderr}")
            return False
        print(f"  fudotext リポジトリへ push 完了")
        return True


def main() -> None:
    parser = argparse.ArgumentParser(description="PDCAフィードバックをgen.pyに自動適用")
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    project = args.project

    cfg = load_config(project)
    product_name = cfg.get("product_name", project)
    fudo_dir = PROJECT_DIR_MAP.get(project, project)

    report_dir = _ROOT / cfg.get(
        "feedback_report_dir",
        f"saas-dev/projects/{project}/feedback_reports"
    )

    print(f"[{product_name}] PDCA 自動適用開始")

    # 最新レポートを探す
    latest_report = find_latest_report(report_dir)
    if not latest_report:
        print("  レポートが見つかりません。スキップします。")
        sys.exit(0)

    print(f"  最新レポート: {latest_report.name}")
    report_content = latest_report.read_text(encoding="utf-8")

    # PROMPT_IMPROVEMENTS を抽出
    improvements = extract_prompt_improvements(report_content)
    if not improvements:
        print("  PROMPT_IMPROVEMENTS: なし。スキップします。")
        sys.exit(0)

    print(f"  改善案:\n{improvements}")

    # gen.py を読み込む
    # ローカル優先、なければ GitHub Actions の clone 先を使う
    local_gen_path = _FUDOTEXT_LOCAL / "saas-dev" / "projects" / fudo_dir / "gen.py"
    is_local = local_gen_path.exists()

    if is_local:
        gen_py_content = local_gen_path.read_text(encoding="utf-8")
        print(f"  gen.py (local): {local_gen_path}")
    else:
        # GitHub Actions: ai-holdings リポジトリ内には gen.py はないので clone が必要
        # ここでは gen.py のサンプルとして空文字を渡して clone 後に処理する
        print("  ローカルに gen.py が見つかりません。GitHub Actions モードで処理します。")
        # apply_via_git_clone に gen.py の読み込みと更新を委ねる
        pat = os.environ.get("FUDOTEXT_PAT", "")
        if not pat:
            print("  [WARN] FUDOTEXT_PAT が未設定。処理をスキップします。")
            sys.exit(0)

        # まず clone して gen.py を読む
        repo_url = f"https://{pat}@github.com/ryuu321/fudotext.git"
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["git", "clone", "--depth=1", repo_url, tmpdir],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                print(f"  [ERROR] git clone 失敗: {result.stderr}")
                sys.exit(1)

            gen_path = Path(tmpdir) / "saas-dev" / "projects" / fudo_dir / "gen.py"
            if not gen_path.exists():
                print(f"  [ERROR] gen.py が見つかりません: {gen_path}")
                sys.exit(1)

            gen_py_content = gen_path.read_text(encoding="utf-8")

            # Gemini で改善
            print("  Gemini でプロンプトを改善中...")
            prompt = build_pdca_prompt(gen_py_content, improvements, product_name)
            try:
                response = call_gemini(prompt)
            except Exception as e:
                print(f"  [ERROR] Gemini 呼び出し失敗: {e}")
                sys.exit(1)

            new_gen_py = extract_code_from_response(response)
            if not new_gen_py:
                print("  [WARN] Gemini からコードを抽出できませんでした。スキップします。")
                sys.exit(0)

            if not is_safe_code(new_gen_py):
                print("  [SECURITY] 危険なコードが検出されました。適用をスキップします。")
                sys.exit(0)

            if new_gen_py.strip() == gen_py_content.strip():
                print("  変更なし（Gemini出力が元コードと同一）。スキップします。")
                sys.exit(0)

            # バックアップ・diff・push
            backup_path = gen_path.with_suffix(".py.bak")
            backup_path.write_text(gen_py_content, encoding="utf-8")

            diff = list(difflib.unified_diff(
                gen_py_content.splitlines(keepends=True),
                new_gen_py.splitlines(keepends=True),
                fromfile="gen.py (before)",
                tofile="gen.py (after)",
                n=3,
            ))
            if diff:
                print("  diff:")
                for line in diff[:50]:
                    print("   " + line.rstrip())

            gen_path.write_text(new_gen_py, encoding="utf-8")

            subprocess.run(["git", "config", "user.email", "actions@github.com"], cwd=tmpdir)
            subprocess.run(["git", "config", "user.name", "Auto Bot"], cwd=tmpdir)
            subprocess.run(["git", "add", str(gen_path)], cwd=tmpdir)

            check = subprocess.run(
                ["git", "diff", "--staged", "--quiet"],
                cwd=tmpdir, capture_output=True
            )
            if check.returncode == 0:
                print("  変更なし")
                sys.exit(0)

            date_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
            commit_msg = f"{project}: PDCA gen.py 自動改善 {date_str} [skip ci]"
            subprocess.run(["git", "commit", "-m", commit_msg], cwd=tmpdir)
            push_result = subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=tmpdir, capture_output=True, text=True
            )
            if push_result.returncode != 0:
                print(f"  [ERROR] git push 失敗: {push_result.stderr}")
                sys.exit(1)

            print(f"  [OK] fudotext リポジトリへ push 完了")
            sys.exit(0)

    # ─── ローカル実行パス ───
    print("  Gemini でプロンプトを改善中...")
    prompt = build_pdca_prompt(gen_py_content, improvements, product_name)
    try:
        response = call_gemini(prompt)
    except Exception as e:
        print(f"  [ERROR] Gemini 呼び出し失敗: {e}")
        sys.exit(1)

    new_gen_py = extract_code_from_response(response)
    if not new_gen_py:
        print("  [WARN] Gemini からコードを抽出できませんでした。スキップします。")
        sys.exit(0)

    if not is_safe_code(new_gen_py):
        print("  [SECURITY] 危険なコードが検出されました。適用をスキップします。")
        sys.exit(0)

    if new_gen_py.strip() == gen_py_content.strip():
        print("  変更なし（Gemini出力が元コードと同一）。スキップします。")
        sys.exit(0)

    apply_to_local_fudotext(project, local_gen_path, new_gen_py, gen_py_content)
    print(f"  [OK] {product_name} gen.py の PDCA 改善を適用しました")


if __name__ == "__main__":
    main()
