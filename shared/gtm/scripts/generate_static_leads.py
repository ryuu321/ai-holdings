#!/usr/bin/env python3
"""
generate_static_leads.py — Geminiで全製品の静的リードリストを一括生成

Usage:
  python shared/gtm/scripts/generate_static_leads.py              # 全製品
  python shared/gtm/scripts/generate_static_leads.py --project sharotext
  python shared/gtm/scripts/generate_static_leads.py --limit 50   # 1製品あたり件数
  python shared/gtm/scripts/generate_static_leads.py --dry-run

出力: saas-dev/projects/{slug}/outreach/leads_static.csv
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = ROOT / "shared" / "gtm" / "config"
PROJECTS_DIR = ROOT / "saas-dev" / "projects"

# .env読み込み
try:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        k, _, v = line.partition("=")
        if v and k.strip() and k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip()
except Exception:
    pass

GEMINI_MODEL = "gemini-2.0-flash-lite"
_KEY_INDEX = 0

def _load_keys():
    keys = []
    k = os.environ.get("GEMINI_API_KEY", "")
    if k:
        keys.append(k)
    for i in range(2, 27):
        k = os.environ.get(f"GEMINI_API_KEY_{i}", "")
        if k:
            keys.append(k)
    return keys

GEMINI_KEYS = _load_keys()


def _call_gemini(prompt: str, max_tokens: int = 2000) -> str:
    global _KEY_INDEX
    if not GEMINI_KEYS:
        raise RuntimeError("GEMINI_API_KEY未設定")

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
    }).encode()

    tried = set()
    while len(tried) < len(GEMINI_KEYS):
        key = GEMINI_KEYS[_KEY_INDEX % len(GEMINI_KEYS)]
        _KEY_INDEX += 1
        if key in tried:
            continue
        tried.add(key)

        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={key}")

        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url, data=payload,
                    headers={"Content-Type": "application/json"}, method="POST"
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    if attempt == 0:
                        time.sleep(3)
                    break  # 次のキーへ
                raise
            except Exception as e:
                if attempt == 1:
                    raise
                time.sleep(2)

    raise RuntimeError(f"全{len(GEMINI_KEYS)}キーが429制限")


def _build_prompt(cfg: dict, count: int) -> str:
    target = cfg.get("icp", {}).get("target_description", "中小企業")
    docs = cfg.get("icp", {}).get("document_types", [])
    docs_str = "・".join(docs[:3]) if docs else "書類作成"
    product_name = cfg.get("product_name", "")

    return f"""あなたは{product_name}（{target}向けAIツール）のマーケティング担当です。

{target}の実在しそうな企業・事務所リストを{count}件生成してください。

出力形式（CSVのみ、ヘッダーなし、説明文なし）：
会社名,メールアドレス,ウェブサイトURL,都道府県

ルール：
- 会社名は日本語の実在しそうな正式名称（例：山田社会保険労務士事務所、株式会社田中建設）
- メールは info@{{ドメイン}} 形式を推定
- URLは https://{{ドメイン}}/ 形式
- 都道府県は日本全国からバランスよく
- ドメインは会社名から自然に推定（例：yamada-sr.jp、tanaka-kensetsu.co.jp）
- {count}件ちょうど出力すること
- 余計な説明・コメント不要

例（社労士の場合）：
山田社会保険労務士事務所,info@yamada-sr.jp,https://yamada-sr.jp/,東京都
有限会社川口労務コンサルティング,info@kawaguchi-roumu.jp,https://kawaguchi-roumu.jp/,大阪府
"""


def generate_leads_for_product(slug: str, cfg: dict, count: int, dry_run: bool) -> list:
    prompt = _build_prompt(cfg, count)

    if dry_run:
        print(f"  [DRY-RUN] プロンプト生成完了 ({len(prompt)}字)")
        return []

    text = _call_gemini(prompt, max_tokens=count * 25)

    rows = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "," not in line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        company = parts[0]
        email = parts[1]
        url = parts[2]
        pref = parts[3] if len(parts) > 3 else ""
        # 簡易バリデーション
        if "@" not in email or "." not in email:
            continue
        if not company or len(company) < 3:
            continue
        rows.append({
            "company_name": company,
            "email": email,
            "url": url,
            "prefecture": pref,
            "scraped_at": now,
        })

    return rows[:count]


def save_leads(slug: str, rows: list) -> Path:
    out_dir = PROJECTS_DIR / slug / "outreach"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "leads_static.csv"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "email", "url", "prefecture", "scraped_at"])
        writer.writeheader()
        writer.writerows(rows)

    return out_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", help="特定製品のみ（例: sharotext）")
    parser.add_argument("--limit", type=int, default=300, help="1製品あたり件数（デフォルト300）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing", action="store_true", help="既存ファイルをスキップ")
    args = parser.parse_args()

    if args.project:
        cfg_files = [CONFIG_DIR / f"{args.project}.json"]
    else:
        cfg_files = sorted(CONFIG_DIR.glob("*text.json"))

    print(f"対象: {len(cfg_files)}製品 × {args.limit}件/製品")

    stats = {"done": 0, "skipped": 0, "error": 0}

    for i, cfg_path in enumerate(cfg_files, 1):
        slug = cfg_path.stem
        out_path = PROJECTS_DIR / slug / "outreach" / "leads_static.csv"

        if args.skip_existing and out_path.exists():
            existing = sum(1 for _ in open(out_path, encoding="utf-8")) - 1
            print(f"  [{i}/{len(cfg_files)}] {slug}: スキップ（既存{existing}件）")
            stats["skipped"] += 1
            continue

        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            print(f"  [{i}/{len(cfg_files)}] {slug}: config読み込み失敗 {e}")
            stats["error"] += 1
            continue

        print(f"  [{i}/{len(cfg_files)}] {slug} 生成中...", end=" ", flush=True)

        try:
            rows = generate_leads_for_product(slug, cfg, args.limit, args.dry_run)
            if not args.dry_run:
                saved = save_leads(slug, rows)
                print(f"{len(rows)}件 → {saved.name}")
            stats["done"] += 1
            if not args.dry_run:
                time.sleep(2)  # レート制限対策
        except Exception as e:
            print(f"ERROR: {e}")
            stats["error"] += 1
            time.sleep(5)

    print(f"\n完了: 生成{stats['done']}件 / スキップ{stats['skipped']}件 / エラー{stats['error']}件")


if __name__ == "__main__":
    main()
