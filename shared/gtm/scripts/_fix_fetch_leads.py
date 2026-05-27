#!/usr/bin/env python3
"""
_fix_fetch_leads.py — 全TextSeries製品の fetch_leads.py を一括パッチ

問題: _extract_company_name() が失敗すると `continue` でURL全スキップ → leads.csv が空
修正: 失敗時に Gemini AI 抽出 → ドメインフォールバックの順で会社名を補完

使い方:
  python shared/gtm/scripts/_fix_fetch_leads.py           # 全製品を更新（書き込みあり）
  python shared/gtm/scripts/_fix_fetch_leads.py --dry-run # 変更差分のみ表示

変更内容:
  - _extract_company_name() の後に Gemini フォールバックを追加
  - `if not company: continue` を `if not company: company = <fallback>` に変更
  - _gemini_extract_company() ヘルパー関数を各 fetch_leads.py に埋め込み
"""

import argparse
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

AI_HOLDINGS = Path(__file__).resolve().parent.parent.parent.parent


# ── パッチ定義 ─────────────────────────────────────────────────────────────────

# fetch_leads.py に追加するヘルパー関数（末尾インジェクション）
_GEMINI_HELPER = '''

# ── Gemini会社名抽出フォールバック（_fix_fetch_leads.py により自動追加） ────────

def _gemini_extract_company(html: str, url: str = "") -> str:
    """
    Gemini Flash Lite で会社名を抽出。
    失敗時はドメイン名を返す（空文字を返さない保証）。
    """
    import json as _json
    import os as _os
    import re as _re
    from urllib.parse import urlparse as _urlparse

    gemini_key = _os.environ.get("GEMINI_API_KEY", "")

    # Gemini API 呼び出し
    if gemini_key and html:
        text = _re.sub(r"<[^>]+>", " ", html)
        text = _re.sub(r"\\s+", " ", text).strip()[:1500]
        prompt = (
            f"以下はウェブサイト（{url}）のテキストです。\\n"
            "このウェブサイトを運営している会社・事務所・法人の正式名称を1つだけ答えてください。\\n"
            "「株式会社○○」「○○社会保険労務士事務所」「○○法人」のような形式で。\\n"
            "わからない場合は「UNKNOWN」とだけ答えてください。余計な説明は不要です。\\n\\n"
            f"テキスト:\\n{text}"
        )
        payload = _json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 30, "temperature": 0},
        }).encode()
        api_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash-lite:generateContent?key={gemini_key}"
        )
        try:
            import urllib.request as _req
            req = _req.Request(
                api_url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with _req.urlopen(req, timeout=15) as r:
                data = _json.loads(r.read())
            name = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            name = name.replace("「", "").replace("」", "").replace("*", "").strip()
            if 2 <= len(name) <= 40 and name != "UNKNOWN":
                return name
        except Exception:
            pass

    # ドメイン名フォールバック
    try:
        domain = _urlparse(url).netloc.lower()
        domain = _re.sub(r"^www\\.", "", domain)
        domain = _re.sub(r"\\.(co\\.jp|or\\.jp|ne\\.jp|gr\\.jp|com|jp|net|org|info)$", "", domain)
        if len(domain) >= 2:
            return domain
    except Exception:
        pass

    return "不明企業"
'''

# 旧コードパターン（`if not company: ... continue` の行）
# fetch_leads.py の実装パターンに合わせて複数バリアント対応
_OLD_PATTERNS = [
    # パターン A: 最もよくあるパターン（aftertext等の標準形）
    (
        re.compile(
            r"([ \t]*company\s*=\s*_extract_company_name\([^\n]+\)\n)"
            r"([ \t]*if\s+not\s+company\s*:\n"
            r"[ \t]*existing\.add\(url\)\n"
            r"[ \t]*continue\n)",
            re.MULTILINE,
        ),
        lambda m: (
            m.group(1)
            + m.group(2).replace(
                "if not company:",
                "if not company:\n"
                + _indent(m.group(2)) + "    company = _gemini_extract_company(html, url)\n"
                + _indent(m.group(2)) + "if not company:",
            )
        ),
    ),
]

# シンプルな文字列置換パターン（regexが複雑すぎる場合の保険）
_SIMPLE_OLD = (
    "                company = _extract_company_name(html, r.get(\"title\", \"\"))\n"
    "                if not company:\n"
    "                    existing.add(url)\n"
    "                    continue\n"
)

_SIMPLE_NEW = (
    "                company = _extract_company_name(html, r.get(\"title\", \"\"))\n"
    "                if not company:\n"
    "                    company = _gemini_extract_company(html, url)\n"
    "                if not company:\n"
    "                    existing.add(url)\n"
    "                    continue\n"
)

# タブインデントバリアント
_SIMPLE_OLD_TAB = (
    "\t\t\t\tcompany = _extract_company_name(html, r.get(\"title\", \"\"))\n"
    "\t\t\t\tif not company:\n"
    "\t\t\t\t\texisting.add(url)\n"
    "\t\t\t\t\tcontinue\n"
)

_SIMPLE_NEW_TAB = (
    "\t\t\t\tcompany = _extract_company_name(html, r.get(\"title\", \"\"))\n"
    "\t\t\t\tif not company:\n"
    "\t\t\t\t\tcompany = _gemini_extract_company(html, url)\n"
    "\t\t\t\tif not company:\n"
    "\t\t\t\t\texisting.add(url)\n"
    "\t\t\t\t\tcontinue\n"
)

# インデントが少ないバリアント（12スペース）
_SIMPLE_OLD_12 = (
    "            company = _extract_company_name(html, r.get(\"title\", \"\"))\n"
    "            if not company:\n"
    "                existing.add(url)\n"
    "                continue\n"
)

_SIMPLE_NEW_12 = (
    "            company = _extract_company_name(html, r.get(\"title\", \"\"))\n"
    "            if not company:\n"
    "                company = _gemini_extract_company(html, url)\n"
    "            if not company:\n"
    "                existing.add(url)\n"
    "                continue\n"
)

_PATCH_PAIRS = [
    (_SIMPLE_OLD, _SIMPLE_NEW),
    (_SIMPLE_OLD_TAB, _SIMPLE_NEW_TAB),
    (_SIMPLE_OLD_12, _SIMPLE_NEW_12),
]

# ヘルパー追加済みの印
_HELPER_MARKER = "# ── Gemini会社名抽出フォールバック（_fix_fetch_leads.py により自動追加）"


def _indent(block: str) -> str:
    """ブロックの先頭行のインデントを返す"""
    for line in block.splitlines():
        if line.strip():
            return re.match(r"([ \t]*)", line).group(1)
    return "                "


def _patch_file(path: Path, dry_run: bool = False) -> str:
    """
    1ファイルにパッチを当てる。
    戻り値: "patched" / "already_patched" / "no_match" / "error"
    """
    try:
        original = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"error: {e}"

    # 既パッチ確認
    if _HELPER_MARKER in original:
        return "already_patched"

    patched = original

    # 文字列置換でパッチ
    matched = False
    for old, new in _PATCH_PAIRS:
        if old in patched:
            patched = patched.replace(old, new)
            matched = True
            break

    # マッチしなかった場合: より柔軟な正規表現で試行
    if not matched:
        # ゆるいパターン: company = _extract_company_name(...) の後の if not company: ... continue
        loose_pattern = re.compile(
            r"([ \t]*)(company\s*=\s*_extract_company_name\([^\n]*\)\n)"
            r"([ \t]*if\s+not\s+company\s*:\s*\n)"
            r"([ \t]*existing\.add\(url\)\s*\n)"
            r"([ \t]*continue\s*\n)",
            re.MULTILINE,
        )
        def _replacer(m):
            indent = m.group(1)
            return (
                m.group(1) + m.group(2)
                + indent + "if not company:\n"
                + indent + "    company = _gemini_extract_company(html, url)\n"
                + m.group(3)
                + m.group(4)
                + m.group(5)
            )
        patched_try = loose_pattern.sub(_replacer, patched)
        if patched_try != patched:
            patched = patched_try
            matched = True

    if not matched:
        return "no_match"

    # ヘルパー関数を末尾に追加（if __name__ == "__main__": の直前）
    main_guard = '\nif __name__ == "__main__":'
    if main_guard in patched:
        idx = patched.index(main_guard)
        patched = patched[:idx] + _GEMINI_HELPER + patched[idx:]
    else:
        patched += _GEMINI_HELPER

    if dry_run:
        # 差分のみ表示
        print(f"  [DRY-RUN] {path.relative_to(AI_HOLDINGS)}")
        _show_diff(original, patched)
        return "patched"

    path.write_text(patched, encoding="utf-8")
    return "patched"


def _show_diff(original: str, patched: str) -> None:
    """変更箇所を簡易表示"""
    orig_lines = original.splitlines()
    patch_lines = patched.splitlines()
    added = sum(1 for l in patch_lines if l not in orig_lines)
    print(f"    +{added} 行追加 / {len(patch_lines) - len(orig_lines):+d} 行差分")


def main():
    parser = argparse.ArgumentParser(description="fetch_leads.py 一括パッチスクリプト")
    parser.add_argument("--dry-run", action="store_true", help="ファイルを変更せず差分のみ表示")
    parser.add_argument("--project", help="特定製品のみ更新（例: sharotext）")
    args = parser.parse_args()

    # 対象ファイルを収集
    outreach_dir = AI_HOLDINGS / "saas-dev" / "projects"
    if args.project:
        targets = list(outreach_dir.glob(f"{args.project}/outreach/fetch_leads.py"))
    else:
        targets = list(outreach_dir.glob("*/outreach/fetch_leads.py"))

    targets = sorted(targets)
    print(f"対象: {len(targets)}件の fetch_leads.py")
    if args.dry_run:
        print("（DRY-RUN モード: ファイル変更なし）\n")

    stats = {"patched": 0, "already_patched": 0, "no_match": 0, "error": 0}

    for path in targets:
        result = _patch_file(path, dry_run=args.dry_run)
        stats[result if result in stats else "error"] += 1
        slug = path.parent.parent.name
        if result == "patched":
            if not args.dry_run:
                print(f"  ✓ {slug}")
        elif result == "already_patched":
            print(f"  - {slug} (パッチ済みスキップ)")
        elif result == "no_match":
            print(f"  ! {slug} (パターン一致なし — 手動確認が必要)")
        else:
            print(f"  ERROR {slug}: {result}")

    print(f"\n完了:")
    print(f"  パッチ適用: {stats['patched']}件")
    print(f"  パッチ済み: {stats['already_patched']}件")
    print(f"  未一致    : {stats['no_match']}件 ← 手動確認が必要")
    print(f"  エラー    : {stats['error']}件")

    if stats["no_match"] > 0:
        print("\n[注意] パターン未一致のファイルは手動でパッチが必要です。")
        print("       fetch_leads.py 内の `if not company: continue` を探して修正してください。")


if __name__ == "__main__":
    main()
