"""
FudoText 日本語SEO記事自動生成
ターゲット: 不動産仲介業者・宅建クラスタ
出力: docs/fudotext/{slug}.html
キーワード: 物件説明文 自動生成 / 不動産 AI ツール / etc.
"""
import os
import re
import urllib.request
import json
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent.parent.parent
DOCS_DIR = _ROOT / "docs" / "fudotext"
SITE_URL = "https://ryuu321.github.io/ai-holdings"
APP_URL = "https://ai-holdings-jarqe7ynu8kkyqsuxdrabs.streamlit.app/"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-1.5-flash-latest"

SEO_TOPICS = [
    {
        "slug": "bukken-setsumei-jidousesei",
        "title": "物件説明文を自動生成するAIツール【無料】不動産仲介業者向け",
        "kw": "物件説明文 自動生成",
        "desc": "SUUMO・at home・HOMESの物件説明文をAIで30秒自動生成。景品表示法対応・文字数自動調整。不動産仲介業者が毎日使える無料ツール。",
    },
    {
        "slug": "fudosan-ai-tool",
        "title": "不動産業務をAIで効率化｜物件説明文・書類作成を自動化する方法",
        "kw": "不動産 AI ツール 無料",
        "desc": "不動産仲介業者がAIで業務効率化する具体的な方法。物件説明文生成から書類作成まで、今日から使える無料AIツールを紹介。",
    },
    {
        "slug": "suumo-bukken-setsumei-kakikata",
        "title": "SUUMO物件説明文の書き方完全ガイド【400字・AI生成対応】",
        "kw": "SUUMO 物件説明文 書き方",
        "desc": "SUUMO掲載用400字の物件説明文の書き方。ターゲット別の訴求ポイント・景品表示法の注意点・AIで自動生成する方法を解説。",
    },
    {
        "slug": "takken-gyosha-gyomu-kouritsuka",
        "title": "宅建業者の業務効率化｜AIで説明文作成時間を30分→30秒に短縮",
        "kw": "宅建業者 業務効率化 AI",
        "desc": "127,000社の宅建業者が直面する物件説明文作成の課題。AIを使って作業時間を95%削減する実践的な方法とツールを紹介。",
    },
    {
        "slug": "keihinhyoji-ho-fudosan-kisei",
        "title": "不動産広告の景品表示法｜違反しやすい表現と自動チェック方法",
        "kw": "景品表示法 不動産 広告 違反",
        "desc": "「最高立地」「一番人気」など不動産広告でよくある景品表示法違反表現を解説。AIによる自動チェックで掲載リスクをゼロに。",
    },
    {
        "slug": "bukken-catchcopy-rei",
        "title": "物件キャッチコピーの作り方｜ファミリー・投資家・単身者別の例文30選",
        "kw": "物件 キャッチコピー 例文",
        "desc": "売れる物件キャッチコピーの法則。ターゲット別に響く言葉・NGワード・AIで自動生成する方法まで、例文30選付きで解説。",
    },
    {
        "slug": "athome-homes-setsumei-chisuu",
        "title": "at home・HOMES物件説明文の文字数と書き方｜ポータル別攻略ガイド",
        "kw": "at home HOMES 物件説明文 文字数",
        "desc": "at home（500字）・HOMES（450字）・SUUMO（400字）の違いと対策。各ポータルで効果的な物件説明文の書き方をAIで自動対応する方法。",
    },
    {
        "slug": "toushi-bukken-setsumei-bunrei",
        "title": "投資物件説明文の書き方｜利回り・賃貸需要・表現例まとめ",
        "kw": "投資物件 説明文 書き方",
        "desc": "投資家向け物件説明文で必須の表現とNG表現。利回り・賃貸需要・エリア特性の訴求方法と、AIで自動生成する具体的な手順。",
    },
]


PAGE_TEMPLATE = """<!DOCTYPE html>
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
.hero{{background:linear-gradient(135deg,#1e3a5f 0%,#2d6a9f 100%);color:#fff;padding:60px 20px;text-align:center}}
.hero h1{{font-size:1.8em;margin-bottom:12px;line-height:1.4;max-width:700px;margin:0 auto 16px}}
.hero p{{font-size:1.05em;opacity:.9;max-width:600px;margin:0 auto 24px}}
.cta{{display:inline-block;background:#f5a623;color:#000;font-weight:700;padding:14px 32px;border-radius:8px;text-decoration:none;font-size:1.05em;margin-top:16px}}
.cta:hover{{background:#e09010}}
.container{{max-width:820px;margin:0 auto;padding:40px 20px}}
.section{{background:#fff;border-radius:12px;padding:32px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
h2{{font-size:1.4em;color:#1e3a5f;margin-bottom:16px;border-left:4px solid #f5a623;padding-left:12px}}
h3{{font-size:1.15em;color:#1e3a5f;margin:20px 0 10px}}
p{{margin-bottom:12px}}
ul{{padding-left:20px;margin:12px 0}}
li{{margin:8px 0}}
.badge{{background:#e3f2fd;color:#1565c0;padding:4px 10px;border-radius:20px;font-size:.85em;font-weight:600;display:inline-block;margin:2px}}
.cta-box{{background:#e8f0fe;border-radius:12px;padding:24px;text-align:center;margin:24px 0}}
table{{width:100%;border-collapse:collapse;margin:16px 0}}
th,td{{border:1px solid #e0e0e0;padding:10px 12px;text-align:left}}
th{{background:#f5f5f5;font-weight:600}}
footer{{text-align:center;padding:32px;color:#666;font-size:.9em}}
</style>
</head>
<body>
<div class="hero">
  <h1>{title}</h1>
  <p>{desc}</p>
  <a class="cta" href="{app_url}" target="_blank">✨ 無料で試してみる</a>
</div>
<div class="container">
{body}
  <div class="cta-box">
    <p style="font-size:1.1em;font-weight:700;margin-bottom:8px">今すぐ無料で試す</p>
    <p style="margin-bottom:16px">登録不要・クレジットカード不要。1分以内に最初の説明文が完成します。</p>
    <a class="cta" href="{app_url}" target="_blank">✨ FudoText を使ってみる</a>
  </div>
  <p style="text-align:center;margin-top:24px"><a href="{site_url}/docs/fudotext.html">← FudoText トップへ戻る</a></p>
</div>
<footer><p>© 2026 FudoText | <a href="{site_url}/docs/fudotext.html">サービスページ</a> | <a href="{app_url}" target="_blank">アプリを開く</a></p>
<p style="margin-top:8px;font-size:.8em;color:#999">AIが生成したコンテンツを含みます。掲載前に必ず内容をご確認ください。</p>
</footer>
</body>
</html>"""


def _generate_body(topic: dict) -> str:
    if not GEMINI_API_KEY:
        return _fallback_body(topic)
    try:
        prompt = f"""不動産仲介業者向けのSEO記事のHTMLボディ部分（<div class="section">タグのみ）を日本語で書いてください。

タイトル: {topic['title']}
メインキーワード: {topic['kw']}
ディスクリプション: {topic['desc']}

要件:
- 1500〜2000字程度
- H2見出し4〜5個（<h2>タグ使用）
- 実務的で具体的な内容（不動産仲介業者が読む前提）
- FudoTextというAIツールを自然に紹介（押しつけがましくない）
- FudoTextの特徴: SUUMO/at home/HOMES対応・ターゲット別生成・景品表示法準拠・無料
- <div class="section">と</div>で各セクションを囲む
- pタグ・ulタグ・tableタグを使って読みやすく
- 最後のセクションはまとめ
- HTMLタグ以外の余計なテキスト（```等）は含めない"""

        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        print(f"  Gemini生成失敗: {e} → フォールバック使用")
        return _fallback_body(topic)


def _fallback_body(topic: dict) -> str:
    return f"""  <div class="section">
    <h2>はじめに：{topic['kw']}の課題</h2>
    <p>不動産仲介業者にとって、物件説明文の作成は毎回30分〜1時間を要する煩わしい作業です。
    SUUMO・at home・HOMESとポータルごとに文字数が異なり、さらに景品表示法に準拠した表現を
    使わなければならないため、ベテランスタッフでも気を遣います。</p>
    <p>本記事では、<strong>{topic['kw']}</strong>に関する実践的な方法と、
    AIを使って作業時間を大幅に短縮する方法をご紹介します。</p>
  </div>
  <div class="section">
    <h2>ポータル別・文字数と注意点</h2>
    <table>
      <tr><th>ポータル</th><th>文字数上限</th><th>主な注意点</th></tr>
      <tr><td>SUUMO</td><td>400字</td><td>簡潔にまとめる・キャッチコピーが重要</td></tr>
      <tr><td>at home</td><td>500字</td><td>設備の詳細を充実させられる</td></tr>
      <tr><td>HOMES</td><td>450字</td><td>ターゲット訴求を明確に</td></tr>
    </table>
    <p>各ポータルに合わせて書き直すのは非効率。AIを使えば、掲載先を選ぶだけで
    自動的に文字数を調整した説明文が生成できます。</p>
  </div>
  <div class="section">
    <h2>景品表示法に気をつけるべき表現</h2>
    <p>不動産広告では以下のような「最大級表現」が景品表示法違反になる場合があります：</p>
    <ul>
      <li>❌「最高の立地」「日本一の眺望」→ 根拠がなければNG</li>
      <li>❌「絶対お得」「必ず値上がり」→ 断言はNG</li>
      <li>❌「一番人気のエリア」→ 根拠なき最大級表現はNG</li>
    </ul>
    <p>FudoTextは、これらのリスク表現を自動検出してブロックする機能を内蔵しています。</p>
  </div>
  <div class="section">
    <h2>AIで説明文を自動生成する手順</h2>
    <p>FudoTextを使えば、以下の3ステップで完了します：</p>
    <ul>
      <li>① 間取り・築年数・駅徒歩・設備を入力（30秒）</li>
      <li>② ターゲット（ファミリー/投資家/単身者など）と掲載先を選択</li>
      <li>③ 生成ボタンを押すとキャッチコピー＋本文が10〜20秒で完成</li>
    </ul>
    <p>生成されたテキストをコピーしてポータルに貼り付けるだけ。30分の作業が30秒になります。</p>
  </div>
  <div class="section">
    <h2>まとめ</h2>
    <p>{topic['kw']}で業務効率化を進めるなら、AIツールの活用が最も効果的です。
    FudoTextは登録不要・無料で試せるため、まず1件の物件で試してみることをおすすめします。</p>
    <p>景品表示法対応・文字数自動調整・ターゲット別生成の3つが揃った専門ツールは、
    仲介業者の物件登録作業を根本から変えます。</p>
  </div>"""


def main():
    print("[fudotext-seo] SEO記事生成開始")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    generated = []
    for topic in SEO_TOPICS:
        out = DOCS_DIR / f"{topic['slug']}.html"
        if out.exists():
            print(f"  スキップ（既存）: {topic['slug']}.html")
            continue

        print(f"  生成中: {topic['slug']} ({topic['kw']})")
        body = _generate_body(topic)
        html = PAGE_TEMPLATE.format(
            title=topic["title"],
            desc=topic["desc"],
            body=body,
            app_url=APP_URL,
            site_url=SITE_URL,
        )
        out.write_text(html, encoding="utf-8")
        generated.append(topic["slug"])
        print(f"  OK docs/fudotext/{topic['slug']}.html")

    # インデックスページ更新
    _update_index()

    print(f"[完了] {len(generated)}件生成")
    return len(generated)


def _update_index():
    index_path = DOCS_DIR / "index.html"
    links = "\n".join(
        f'      <li><a href="{t["slug"]}.html">{t["title"]}</a></li>'
        for t in SEO_TOPICS
    )
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FudoText — 不動産物件説明文AIツール 完全ガイド</title>
<meta name="description" content="不動産仲介業者向けAI自動生成ツールFudoTextの完全ガイド。SUUMO/at home/HOMES対応・景品表示法準拠・無料。">
<meta name="robots" content="index, follow">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Yu Gothic',sans-serif;color:#1a1a2e;background:#f8f9ff;line-height:1.8}}
.hero{{background:linear-gradient(135deg,#1e3a5f 0%,#2d6a9f 100%);color:#fff;padding:60px 20px;text-align:center}}
.hero h1{{font-size:2em;margin-bottom:12px}}
.cta{{display:inline-block;background:#f5a623;color:#000;font-weight:700;padding:14px 32px;border-radius:8px;text-decoration:none;font-size:1.05em;margin-top:16px}}
.container{{max-width:820px;margin:0 auto;padding:40px 20px}}
.section{{background:#fff;border-radius:12px;padding:32px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
h2{{font-size:1.4em;color:#1e3a5f;margin-bottom:16px;border-left:4px solid #f5a623;padding-left:12px}}
ul{{padding-left:20px;margin:12px 0}}
li{{margin:8px 0}}
a{{color:#1e3a5f}}
footer{{text-align:center;padding:32px;color:#666;font-size:.9em}}
</style>
</head>
<body>
<div class="hero">
  <h1>FudoText — 物件説明文AIガイド</h1>
  <p style="opacity:.9;margin-top:8px">不動産仲介業者向け完全ガイド集</p>
  <a class="cta" href="{APP_URL}" target="_blank">✨ 無料で試してみる</a>
</div>
<div class="container">
  <div class="section">
    <h2>ガイド一覧</h2>
    <ul>
{links}
    </ul>
  </div>
  <div class="section">
    <h2>FudoTextについて</h2>
    <p>FudoTextは不動産仲介業者専用のAI物件説明文生成ツールです。
    SUUMO・at home・HOMESの文字数に自動対応し、景品表示法に準拠した
    説明文を30秒で生成します。</p>
    <p><a href="{SITE_URL}/docs/fudotext.html">→ サービス詳細ページ</a></p>
  </div>
</div>
<footer><p>© 2026 FudoText | <a href="{APP_URL}" target="_blank">アプリを開く</a></p></footer>
</body>
</html>"""
    index_path.write_text(html, encoding="utf-8")
    print("  OK docs/fudotext/index.html")


if __name__ == "__main__":
    main()
