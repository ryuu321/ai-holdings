#!/usr/bin/env python3
"""
generate_note_articles.py — TextSeries 全製品の note.com 投稿用記事を一括生成

使い方:
  python shared/gtm/scripts/generate_note_articles.py              # 全製品
  python shared/gtm/scripts/generate_note_articles.py --project sharotext  # 1製品
  python shared/gtm/scripts/generate_note_articles.py --dry-run   # プロンプトのみ表示
  python shared/gtm/scripts/generate_note_articles.py --skip-existing  # 生成済みはスキップ

入力:  shared/gtm/config/{slug}.json
出力:  shared/gtm/content/note/{slug}_article.md

記事フォーマット:
  1. 共感できる課題の描写（約200字）
  2. 解決策の提示（約300字）
  3. 製品紹介（約200字）
  4. まとめ + CTA（約100字）
  合計: 800〜1200文字
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

AI_HOLDINGS = Path(__file__).resolve().parent.parent.parent.parent
GTM_DIR = AI_HOLDINGS / "shared" / "gtm"
CONFIG_DIR = GTM_DIR / "config"
OUTPUT_DIR = GTM_DIR / "content" / "note"

# .envを読む
try:
    env_path = AI_HOLDINGS / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if v and k.strip() and k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()
except Exception:
    pass

GEMINI_MODEL = "gemini-2.0-flash-lite"

# API呼び出し間隔（レート制限対策）
API_INTERVAL = 2.0

# 全APIキーをローテーション
_GEMINI_KEYS: list[str] = []
_key_index = 0

def _load_gemini_keys() -> list[str]:
    keys = []
    # GEMINI_API_KEY, GEMINI_API_KEY_2 ... GEMINI_API_KEY_26
    k = os.environ.get("GEMINI_API_KEY", "")
    if k:
        keys.append(k)
    for i in range(2, 27):
        k = os.environ.get(f"GEMINI_API_KEY_{i}", "")
        if k:
            keys.append(k)
    return keys

_GEMINI_KEYS = _load_gemini_keys()

# ── Gemini helper ──────────────────────────────────────────────────────────────

def _call_gemini(prompt: str, max_tokens: int = 1200) -> str:
    """Gemini Flash Lite に prompt を送って応答テキストを返す（全キーローテーション）"""
    global _key_index
    if not _GEMINI_KEYS:
        raise RuntimeError("GEMINI_API_KEY が未設定です。.env に追加してください。")

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7,
            "topP": 0.9,
        },
    }).encode()

    tried = set()
    while len(tried) < len(_GEMINI_KEYS):
        key = _GEMINI_KEYS[_key_index % len(_GEMINI_KEYS)]
        _key_index += 1
        if key in tried:
            continue
        tried.add(key)

        api_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{GEMINI_MODEL}:generateContent?key={key}"
        )

        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    api_url, data=payload,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()

            except urllib.error.HTTPError as e:
                if e.code == 429:
                    if attempt < 2:
                        wait = 2 ** (attempt + 1)
                        print(f"    Gemini 429 → {wait}s待機...")
                        time.sleep(wait)
                    else:
                        break  # このキーは限界、次のキーへ
                else:
                    raise
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"    リトライ ({attempt + 1}/3): {e}")
                time.sleep(2)

    raise RuntimeError(f"全{len(_GEMINI_KEYS)}キーが429制限。後でリトライしてください。")


# ── プロンプト生成 ─────────────────────────────────────────────────────────────

def _build_prompt(cfg: dict) -> str:
    """configから note 記事生成プロンプトを構築"""
    product_name = cfg["product_name"]
    target = cfg.get("icp", {}).get("target_description", "中小企業")
    docs = cfg.get("icp", {}).get("document_types", [])
    docs_str = "、".join(docs[:3]) if docs else "書類作成"
    app_url = cfg.get("app_url", "")
    stripe_url = cfg.get("stripe_standard_url", "")
    lp_url = cfg.get("lp_url", app_url)

    # feedback_prompt_context があれば課題の文脈に使う
    pain_context = cfg.get("feedback_prompt_context", "")
    pain_point = f"{docs_str}の効率化"

    prompt = f"""あなたは{product_name}（{target}向けAIツール）のマーケター。
note.comに投稿する記事を書いてください。

テーマ: 「{target}の{pain_point}をAIで解決する方法」
文字数: 800〜1200文字（厳守）
トーン: 親しみやすいが専門的。業界従事者が「わかる！」と感じる言葉を使う。

構成（各セクションはH2見出しで区切る）:
1. ## {target}なら誰もが感じる「あの課題」（約200字）
   - 具体的な場面描写。「毎回同じ書類を…」「手書きで何枚も…」などの共感ポイント
   - ターゲット: {target}

2. ## AIがその課題を根本から変える（約300字）
   - 解決策の原理を平易に説明
   - {docs_str}のような具体的な書類名を出す
   - 「入力すれば自動生成」「数分で完成」など具体的ベネフィット

3. ## {product_name}とは（約200字）
   - 製品の機能・特徴を簡潔に
   - 無料トライアルへの言及
   - アプリURL: {app_url}

4. ## まとめ + 今すぐ試してみる（約100字）
   - 行動を促す締め
   - 無料で試す: {lp_url or app_url}
   - 有料プランはこちら: {stripe_url}

制約:
- 最大級表現（最高・最良・日本一等）は使わない
- 「AI」「自動化」「効率化」の言葉は合計5回以下
- 記事タイトルは冒頭に「# 」で1行目に記載すること
- マークダウン形式で出力
{f'- 製品背景: {pain_context[:200]}' if pain_context else ''}
"""
    return prompt


# ── 記事生成 ──────────────────────────────────────────────────────────────────

def generate_article(cfg: dict, dry_run: bool = False) -> str:
    """1製品の記事を生成して返す"""
    prompt = _build_prompt(cfg)

    if dry_run:
        print(f"  [DRY-RUN] プロンプト ({len(prompt)}文字):")
        print("  " + "\n  ".join(prompt.splitlines()[:5]) + "\n  ...")
        return f"# {cfg['product_name']}の記事（dry-runにつき未生成）\n"

    return _call_gemini(prompt, max_tokens=1400)


def save_article(slug: str, content: str) -> Path:
    """記事をファイルに保存"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{slug}_article.md"
    out_path.write_text(content, encoding="utf-8")
    return out_path


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="TextSeries note記事一括生成")
    parser.add_argument("--project", help="特定製品のみ生成（例: sharotext）")
    parser.add_argument("--dry-run", action="store_true", help="プロンプトのみ表示・API未呼び出し")
    parser.add_argument("--skip-existing", action="store_true", help="生成済みファイルをスキップ")
    parser.add_argument("--limit", type=int, default=0, help="生成上限件数（0=無制限）")
    args = parser.parse_args()

    # 対象configファイルを収集
    if args.project:
        config_files = [CONFIG_DIR / f"{args.project}.json"]
        if not config_files[0].exists():
            print(f"設定ファイルが見つかりません: {config_files[0]}")
            sys.exit(1)
    else:
        config_files = sorted(CONFIG_DIR.glob("*text.json"))  # TextSeriesのみ

    print(f"対象: {len(config_files)}製品")
    if not _GEMINI_KEYS and not args.dry_run:
        print("ERROR: GEMINI_API_KEY が未設定です。.env に追加してください。")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    stats = {"generated": 0, "skipped": 0, "error": 0}
    limit = args.limit if args.limit > 0 else len(config_files)

    for i, cfg_path in enumerate(config_files, 1):
        if stats["generated"] >= limit and not args.dry_run:
            break

        slug = cfg_path.stem  # ファイル名から拡張子除去

        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except Exception as e:
            print(f"  [{i}] ERROR 設定読み込み失敗 {slug}: {e}")
            stats["error"] += 1
            continue

        out_path = OUTPUT_DIR / f"{slug}_article.md"

        # スキップ判定
        if args.skip_existing and out_path.exists():
            print(f"  [{i}/{len(config_files)}] - {slug} (生成済みスキップ)")
            stats["skipped"] += 1
            continue

        print(f"  [{i}/{len(config_files)}] 生成中: {cfg.get('product_name', slug)} ...", end=" ")

        try:
            content = generate_article(cfg, dry_run=args.dry_run)
            if args.dry_run:
                stats["generated"] += 1
                continue
            saved = save_article(slug, content)
            char_count = len(content)
            print(f"{char_count}字 → {saved.name}")
            stats["generated"] += 1

            # レート制限対策（dry-runは不要）
            if not args.dry_run and i < len(config_files):
                time.sleep(API_INTERVAL)

        except KeyboardInterrupt:
            print("\n中断しました。")
            break
        except Exception as e:
            print(f"ERROR: {e}")
            stats["error"] += 1
            time.sleep(5)  # エラー後は少し待つ

    print(f"\n完了:")
    print(f"  生成: {stats['generated']}件 → {OUTPUT_DIR}")
    print(f"  スキップ: {stats['skipped']}件")
    print(f"  エラー: {stats['error']}件")


if __name__ == "__main__":
    main()
