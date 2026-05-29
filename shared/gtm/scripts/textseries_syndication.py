#!/usr/bin/env python3
"""
textseries_syndication.py — TextSeries 全製品を Qiita / Dev.to に毎日シンジケーション

毎日N製品（日付ローテーション）のコンテンツを生成・投稿する。
既投稿はスキップ（冪等）。

Usage:
  python shared/gtm/scripts/textseries_syndication.py            # 今日の担当製品
  python shared/gtm/scripts/textseries_syndication.py --project sharotext
  python shared/gtm/scripts/textseries_syndication.py --per-day 3
  python shared/gtm/scripts/textseries_syndication.py --dry-run
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT       = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = ROOT / "shared" / "gtm" / "config"
STATE_DIR  = ROOT / "shared" / "gtm" / "state"
STATE_FILE = STATE_DIR / "syndication_state.json"
MODEL      = "gemini-2.0-flash-lite"
SKIP_CONFIGS = {"gcp_pools.json", "gist_ids.json"}

QIITA_TOKEN = os.environ.get("QIITA_ACCESS_TOKEN", "")
DEVTO_KEY   = os.environ.get("DEVTO_API_KEY", "")


# --- Gemini key rotation ---

def _load_keys() -> list[str]:
    keys = []
    for i in range(1, 27):
        k = os.environ.get(f"GEMINI_API_KEY_{i}") or os.environ.get("GEMINI_API_KEY")
        if k and k not in keys:
            keys.append(k)
    if not keys:
        k = os.environ.get("GEMINI_API_KEY", "")
        if k:
            keys.append(k)
    return keys

_KEYS    = _load_keys()
_KEY_IDX = 0


def _call_gemini(prompt: str) -> str:
    global _KEY_IDX
    if not _KEYS:
        return ""
    for attempt in range(len(_KEYS)):
        key = _KEYS[(_KEY_IDX + attempt) % len(_KEYS)]
        try:
            payload = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.8, "maxOutputTokens": 3000},
            }).encode("utf-8")
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={key}",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                _KEY_IDX = (_KEY_IDX + attempt + 1) % len(_KEYS)
                return data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception as e:
            err = str(e)
            if "429" in err or "QUOTA" in err.upper() or "503" in err:
                time.sleep(3)
                continue
            print(f"  Gemini失敗: {err[:80]}")
            return ""
    return ""


# --- Content generation ---

def _gen_qiita_article(cfg: dict) -> dict:
    product_name = cfg["product_name"]
    target       = cfg["icp"]["target_description"]
    docs         = cfg["icp"]["document_types"]
    app_url      = cfg["app_url"]
    lp_url       = cfg["lp_url"]

    prompt = f"""以下の業務効率化ツールについて、Qiitaに投稿するMarkdown記事を書いてください。

製品名: {product_name}
対象: {target}
AIで生成できる書類: {', '.join(docs[:5])}
アプリURL: {app_url}

要件:
- タイトル: 「{target}がAIで書類作成を効率化する方法」系（40〜60字）
- 文字数: 1500〜2000字
- 見出し（##）を4〜5個
- 実務的・具体的な内容（手順・メリット・注意点）
- {product_name}を自然に紹介（最後のセクションでCTAとして）
- 最初の行は # タイトル
- Markdown形式

JSON形式で返してください（コードブロック不要）:
{{
  "title": "記事タイトル",
  "body": "Markdown本文全体",
  "tags": ["タグ1", "タグ2", "タグ3"]
}}"""

    raw = _call_gemini(prompt)
    if not raw:
        return {}
    try:
        s = raw.find("{")
        e = raw.rfind("}") + 1
        return json.loads(raw[s:e])
    except Exception:
        return {}


def _gen_devto_article(cfg: dict) -> dict:
    product_name = cfg["product_name"]
    target       = cfg["icp"]["target_description"]
    docs         = cfg["icp"]["document_types"]
    app_url      = cfg["app_url"]

    prompt = f"""Write an English blog post for Dev.to about the following B2B SaaS tool.

Product: {product_name}
Target users: {target} (Japanese SME)
Generates documents like: {', '.join(docs[:5])}
App URL: {app_url}

Requirements:
- Title: practical, developer/founder friendly (50-70 chars)
- Length: 800-1200 words
- 3-4 sections with ## headings
- Angle: "building niche SaaS for Japanese SMEs" or practical AI doc automation
- Natural mention of {product_name} as example/case study
- End with brief CTA to try free trial

Return JSON only (no code block):
{{
  "title": "article title",
  "body": "full markdown body",
  "tags": ["tag1", "tag2", "tag3", "tag4"]
}}"""

    raw = _call_gemini(prompt)
    if not raw:
        return {}
    try:
        s = raw.find("{")
        e = raw.rfind("}") + 1
        return json.loads(raw[s:e])
    except Exception:
        return {}


# --- API posting ---

def _post_qiita(title: str, body: str, tags: list[str]) -> str:
    if not QIITA_TOKEN:
        print("  QIITA_ACCESS_TOKEN 未設定 → スキップ")
        return ""
    tag_objs = [{"name": t[:20], "versions": []} for t in (tags or ["AI", "業務効率化"])[:5]]
    payload = json.dumps({
        "title": title,
        "body": body,
        "private": False,
        "tags": tag_objs,
        "tweet": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://qiita.com/api/v2/items",
        data=payload,
        headers={
            "Authorization": f"Bearer {QIITA_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            return data.get("url", "")
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace")[:200]
        print(f"  Qiita投稿失敗 {e.code}: {body_err}")
        return ""


def _post_devto(title: str, body: str, tags: list[str]) -> str:
    if not DEVTO_KEY:
        print("  DEVTO_API_KEY 未設定 → スキップ")
        return ""
    payload = json.dumps({
        "article": {
            "title": title,
            "body_markdown": body,
            "published": True,
            "tags": [t.lower().replace(" ", "") for t in (tags or ["javascript"])[:4]],
        }
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://dev.to/api/articles",
        data=payload,
        headers={
            "api-key": DEVTO_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            return data.get("url", "")
    except urllib.error.HTTPError as e:
        body_err = e.read().decode("utf-8", errors="replace")[:200]
        print(f"  Dev.to投稿失敗 {e.code}: {body_err}")
        return ""


# --- State management ---

def _load_state() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"qiita": {}, "devto": {}}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# --- Main ---

def _get_today_projects(all_configs: list[Path], per_day: int) -> list[Path]:
    day_idx = date.today().timetuple().tm_yday - 1
    total   = len(all_configs)
    start   = (day_idx * per_day) % total
    selected = []
    for i in range(per_day):
        selected.append(all_configs[(start + i) % total])
    return selected


def process(cfg_path: Path, dry_run: bool, state: dict) -> bool:
    cfg     = json.loads(cfg_path.read_text(encoding="utf-8"))
    project = cfg.get("project", "")
    product = cfg.get("product_name", project)
    if not project:
        return False

    print(f"\n[{project}] {product}")

    posted_any = False

    # --- Qiita ---
    if project not in state["qiita"]:
        print("  Qiita記事生成中...")
        art = _gen_qiita_article(cfg)
        if art and art.get("title") and art.get("body"):
            if dry_run:
                print(f"  [DRY] Qiita: {art['title']}")
                state["qiita"][project] = "dry-run"
            else:
                url = _post_qiita(art["title"], art["body"], art.get("tags", []))
                if url:
                    print(f"  Qiita投稿完了: {url}")
                    state["qiita"][project] = url
                    posted_any = True
                    time.sleep(2)
        else:
            print("  Qiita記事生成失敗")
    else:
        print(f"  Qiita: 投稿済み → スキップ")

    # --- Dev.to ---
    if project not in state["devto"]:
        print("  Dev.to記事生成中...")
        art = _gen_devto_article(cfg)
        if art and art.get("title") and art.get("body"):
            if dry_run:
                print(f"  [DRY] Dev.to: {art['title']}")
                state["devto"][project] = "dry-run"
            else:
                url = _post_devto(art["title"], art["body"], art.get("tags", []))
                if url:
                    print(f"  Dev.to投稿完了: {url}")
                    state["devto"][project] = url
                    posted_any = True
                    time.sleep(2)
        else:
            print("  Dev.to記事生成失敗")
    else:
        print(f"  Dev.to: 投稿済み → スキップ")

    return posted_any


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="")
    parser.add_argument("--per-day", type=int, default=3,
                        help="製品あたり1日の投稿数（デフォルト3）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    configs = sorted(CONFIG_DIR.glob("*.json"))
    configs = [c for c in configs if c.name not in SKIP_CONFIGS]

    if args.project:
        configs = [c for c in configs if c.stem == args.project]
        if not configs:
            print(f"設定ファイルが見つかりません: {args.project}")
            sys.exit(1)
        targets = configs
    else:
        targets = _get_today_projects(configs, args.per_day)

    state = _load_state()

    total = 0
    for cfg_path in targets:
        if process(cfg_path, args.dry_run, state):
            total += 1
        _save_state(state)

    print(f"\n[完了] {total}製品を新規投稿")


if __name__ == "__main__":
    main()
