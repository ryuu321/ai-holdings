#!/usr/bin/env python3
"""
generate_seo_pages.py — TextSeries 全製品 SEO記事自動生成

各製品の config JSON を読み込み、業種特化 SEO 記事 HTML を
docs/{project}/ に生成する。既存ファイルはスキップ（冪等）。

Usage:
  python shared/gtm/scripts/generate_seo_pages.py            # 全製品
  python shared/gtm/scripts/generate_seo_pages.py --project sharotext
  python shared/gtm/scripts/generate_seo_pages.py --limit 3  # 製品あたり記事数上限
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_DIR = ROOT / "shared" / "gtm" / "config"
DOCS_DIR = ROOT / "docs"
SITE_URL = "https://ryuu321.github.io/ai-holdings"
MODEL = "gemini-2.0-flash-lite"

SKIP_CONFIGS = {"gcp_pools.json", "gist_ids.json"}

# Geminiキーローテーション
def _load_keys():
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

_KEYS = _load_keys()
_KEY_IDX = 0

def _call_gemini(prompt: str) -> str:
    global _KEY_IDX
    for attempt in range(len(_KEYS)):
        key = _KEYS[(_KEY_IDX + attempt) % len(_KEYS)]
        try:
            payload = json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048},
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
                time.sleep(2)
                continue
            print(f"  Gemini失敗 ({err[:60]})")
            return ""
    return ""


def _generate_topics(cfg: dict) -> list[dict]:
    """製品設定から SEO トピックリストを Gemini で生成"""
    product_name = cfg["product_name"]
    target = cfg["icp"]["target_description"]
    docs = cfg["icp"]["document_types"]

    prompt = f"""以下のSaaS製品向けにSEO記事トピックを5件生成してください。

製品名: {product_name}
対象顧客: {target}
生成できる書類: {', '.join(docs[:5])}

各トピックは以下のJSON配列形式で返してください（コードブロック不要）:
[
  {{
    "slug": "url-friendly-slug",
    "title": "SEO記事タイトル（40〜60字）",
    "kw": "メインキーワード（10〜20字）",
    "desc": "メタディスクリプション（80〜120字）"
  }}
]

要件:
- slugは英小文字・ハイフンのみ
- 対象顧客が検索しそうなキーワードを使う（業務効率化・書類作成・AI活用等）
- {product_name}を自然に訴求できるトピックにする
- JSON配列のみ返す（説明文不要）"""

    raw = _call_gemini(prompt)
    if not raw:
        return []
    try:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        return json.loads(raw[start:end])
    except Exception:
        return []


PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta name="robots" content="index, follow">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Yu Gothic',sans-serif;color:#1a1a2e;background:#f8f9ff;line-height:1.8}}
.hero{{background:linear-gradient(135deg,#1a2a4a 0%,#2d5a8f 100%);color:#fff;padding:60px 20px;text-align:center}}
.hero h1{{font-size:1.8em;margin-bottom:12px;line-height:1.4;max-width:700px;margin:0 auto 16px}}
.hero p{{font-size:1.05em;opacity:.9;max-width:600px;margin:0 auto 24px}}
.cta{{display:inline-block;background:#f5a623;color:#000;font-weight:700;padding:14px 32px;border-radius:8px;text-decoration:none;font-size:1.05em;margin-top:16px}}
.cta:hover{{background:#e09010}}
.container{{max-width:820px;margin:0 auto;padding:40px 20px}}
.section{{background:#fff;border-radius:12px;padding:32px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
h2{{font-size:1.4em;color:#1a2a4a;margin-bottom:16px;border-left:4px solid #f5a623;padding-left:12px}}
h3{{font-size:1.15em;color:#1a2a4a;margin:20px 0 10px}}
p{{margin-bottom:12px}}
ul{{padding-left:20px;margin:12px 0}}
li{{margin:8px 0}}
.cta-box{{background:#e8f0fe;border-radius:12px;padding:24px;text-align:center;margin:24px 0}}
table{{width:100%;border-collapse:collapse;margin:16px 0}}
th,td{{border:1px solid #e0e0e0;padding:10px 12px;text-align:left}}
th{{background:#f5f5f5;font-weight:600}}
footer{{text-align:center;padding:32px;color:#666;font-size:.9em}}
a{{color:#1a2a4a}}
</style>
</head>
<body>
<div class="hero">
  <h1>{title}</h1>
  <p>{desc}</p>
  <a class="cta" href="{app_url}" target="_blank">✨ 無料で試してみる（5件）</a>
</div>
<div class="container">
{body}
  <div class="cta-box">
    <p style="font-size:1.1em;font-weight:700;margin-bottom:8px">今すぐ無料で試す</p>
    <p style="margin-bottom:16px">登録不要・クレジットカード不要。5件まで無料でお試しいただけます。</p>
    <a class="cta" href="{app_url}" target="_blank">✨ {product_name} を使ってみる</a>
  </div>
  <p style="text-align:center;margin-top:24px"><a href="{lp_url}">← {product_name} トップへ戻る</a></p>
</div>
<footer>
  <p>© 2026 {product_name} | <a href="{lp_url}">サービスページ</a> | <a href="{app_url}" target="_blank">アプリを開く</a></p>
  <p style="margin-top:8px;font-size:.8em;color:#999">AIが生成したコンテンツを含みます。掲載前に必ず内容をご確認ください。</p>
  <p style="margin-top:8px"><a href="{site_url}/" style="color:#999">他の業種向けAIツールを見る → TextSeries 製品一覧</a></p>
</footer>
</body>
</html>"""


def _generate_body(topic: dict, cfg: dict) -> str:
    product_name = cfg["product_name"]
    target = cfg["icp"]["target_description"]
    docs = cfg["icp"]["document_types"]

    prompt = f"""{target}向けのSEO記事のHTMLボディ部分を日本語で書いてください。

タイトル: {topic['title']}
メインキーワード: {topic['kw']}
製品名: {product_name}
対象読者: {target}
製品で生成できる書類: {', '.join(docs[:5])}

要件:
- 1500〜2000字程度
- <div class="section">タグでセクションを囲む
- H2見出し4〜5個（<h2>タグ）
- 実務的・具体的な内容
- {product_name}を自然に紹介（押しつけがましくない）
- 特徴: 無料トライアル5件・AI書類生成・30秒・登録不要
- pタグ・ulタグ・tableタグを使って読みやすく
- 最後のセクションはまとめ
- HTMLタグ以外の余計なテキスト（```等）は含めない"""

    body = _call_gemini(prompt)
    if body:
        return body

    # フォールバック
    doc_list = "・".join(docs[:3])
    return f"""  <div class="section">
    <h2>{topic['kw']}の課題</h2>
    <p>{target}にとって、{doc_list}などの書類作成は専門的な知識と時間を要する業務です。
    毎回ゼロから作成するのは非効率であり、ミスのリスクも伴います。</p>
    <p>本記事では、<strong>{topic['kw']}</strong>に関する実践的な方法と、
    AIを使って作業時間を大幅に短縮する方法をご紹介します。</p>
  </div>
  <div class="section">
    <h2>{product_name}でできること</h2>
    <p>{product_name}は{target}向けに特化したAI書類生成ツールです。
    以下の書類を数十秒でドラフト生成できます：</p>
    <ul>
      {''.join(f'<li>{d}</li>' for d in docs[:5])}
    </ul>
    <p>登録不要・クレジットカード不要で5件まで無料でお試しいただけます。</p>
  </div>
  <div class="section">
    <h2>AIで書類作成を効率化する手順</h2>
    <p>{product_name}の使い方は簡単3ステップです：</p>
    <ul>
      <li>① 必要情報を入力フォームに入力（1〜2分）</li>
      <li>② 書類の種類を選択</li>
      <li>③ 生成ボタンを押すと30秒以内にドラフトが完成</li>
    </ul>
    <p>生成されたドラフトを確認・修正して完成です。作業時間を大幅に削減できます。</p>
  </div>
  <div class="section">
    <h2>まとめ</h2>
    <p>{topic['kw']}での業務効率化には、業種特化AIツールの活用が効果的です。
    {product_name}は{target}の実務に特化して設計されており、
    現場で即使えるドラフトを生成します。</p>
    <p>まず無料で5件試して、業務への適合性をご確認ください。</p>
  </div>"""


def _write_index(product_dir: Path, cfg: dict, topics: list[dict]):
    product_name = cfg["product_name"]
    lp_url = cfg["lp_url"]
    app_url = cfg["app_url"]

    links = "\n".join(
        f'      <li><a href="{t["slug"]}.html">{t["title"]}</a></li>'
        for t in topics
    )
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{product_name} — 完全ガイド集</title>
<meta name="description" content="{cfg['icp']['target_description']}向けAIツール{product_name}の完全ガイド集。無料トライアル5件。">
<meta name="robots" content="index, follow">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Yu Gothic',sans-serif;color:#1a1a2e;background:#f8f9ff;line-height:1.8}}
.hero{{background:linear-gradient(135deg,#1a2a4a 0%,#2d5a8f 100%);color:#fff;padding:60px 20px;text-align:center}}
.hero h1{{font-size:2em;margin-bottom:12px}}
.cta{{display:inline-block;background:#f5a623;color:#000;font-weight:700;padding:14px 32px;border-radius:8px;text-decoration:none;margin-top:16px}}
.container{{max-width:820px;margin:0 auto;padding:40px 20px}}
.section{{background:#fff;border-radius:12px;padding:32px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
h2{{font-size:1.4em;color:#1a2a4a;margin-bottom:16px;border-left:4px solid #f5a623;padding-left:12px}}
ul{{padding-left:20px;margin:12px 0}} li{{margin:8px 0}} a{{color:#1a2a4a}}
footer{{text-align:center;padding:32px;color:#666;font-size:.9em}}
</style>
</head>
<body>
<div class="hero">
  <h1>{product_name} — 完全ガイド</h1>
  <p style="opacity:.9;margin-top:8px">{cfg['icp']['target_description']}向け AI 書類生成ツール</p>
  <a class="cta" href="{app_url}" target="_blank">✨ 無料で試してみる</a>
</div>
<div class="container">
  <div class="section">
    <h2>ガイド一覧</h2>
    <ul>
{links}
    </ul>
  </div>
  <div class="section">
    <h2>{product_name}について</h2>
    <p>{product_name}は{cfg['icp']['target_description']}向けに特化したAI書類生成ツールです。
    登録不要・クレジットカード不要で5件まで無料でお試しいただけます。</p>
    <p><a href="{lp_url}">→ サービス詳細ページ</a></p>
  </div>
</div>
<footer>
  <p>© 2026 {product_name} | <a href="{app_url}" target="_blank">アプリを開く</a></p>
  <p style="margin-top:8px"><a href="{SITE_URL}/" style="color:#999">他の業種向けAIツールを見る → TextSeries 製品一覧</a></p>
</footer>
</body>
</html>"""
    (product_dir / "index.html").write_text(html, encoding="utf-8")


def process_product(cfg_path: Path, limit: int) -> int:
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    project = cfg.get("project", "")
    if not project:
        return 0

    product_dir = DOCS_DIR / project
    product_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[{project}] SEO記事生成開始")

    # 既存トピックを topics キャッシュファイルから読む（生成コスト節約）
    cache_path = product_dir / "_topics.json"
    if cache_path.exists():
        topics = json.loads(cache_path.read_text(encoding="utf-8"))
        print(f"  トピックキャッシュ読み込み: {len(topics)}件")
    else:
        print(f"  Geminiでトピック生成中...")
        topics = _generate_topics(cfg)
        if not topics:
            print(f"  トピック生成失敗 → スキップ")
            return 0
        cache_path.write_text(json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  トピック{len(topics)}件生成")

    generated = 0
    for topic in topics[:limit]:
        out = product_dir / f"{topic['slug']}.html"
        if out.exists():
            print(f"  スキップ（既存）: {topic['slug']}.html")
            continue

        print(f"  生成中: {topic['kw']}")
        body = _generate_body(topic, cfg)
        html = PAGE_TEMPLATE.format(
            title=topic["title"],
            desc=topic["desc"],
            body=body,
            app_url=cfg["app_url"],
            lp_url=cfg["lp_url"],
            product_name=cfg["product_name"],
            site_url=SITE_URL,
        )
        out.write_text(html, encoding="utf-8")
        generated += 1
        print(f"  OK: docs/{project}/{topic['slug']}.html")
        time.sleep(1)

    _write_index(product_dir, cfg, topics)
    print(f"  [{project}] {generated}件生成 / index.html更新")
    return generated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    configs = sorted(CONFIG_DIR.glob("*.json"))
    configs = [c for c in configs if c.name not in SKIP_CONFIGS]

    if args.project:
        configs = [c for c in configs if c.stem == args.project]
        if not configs:
            print(f"設定ファイルが見つかりません: {args.project}")
            sys.exit(1)

    total = 0
    for cfg_path in configs:
        total += process_product(cfg_path, args.limit)

    print(f"\n[完了] 合計{total}件のSEO記事を生成しました")


if __name__ == "__main__":
    main()
