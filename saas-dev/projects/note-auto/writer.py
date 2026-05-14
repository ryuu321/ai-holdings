"""
writer.py — Geminiで記事を生成する
"""
import os
import re
import json
import time
from pathlib import Path

try:
    from google import genai
except ImportError:
    print("pip install google-genai")
    exit(1)

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                API_KEY = line.split("=", 1)[1].strip()
                break

client = genai.Client(api_key=API_KEY)
MODEL = "gemini-flash-latest"

SEPARATOR = "|||SPLIT|||"
AFFILIATE_FILE = Path(__file__).parent / "data" / "affiliate_links.json"


def load_best_affiliate(account_id: int) -> dict | None:
    """アカウントテーマに合う最高単価のアフィリ案件を返す"""
    if not AFFILIATE_FILE.exists():
        return None
    try:
        data = json.loads(AFFILIATE_FILE.read_text(encoding="utf-8"))
        progs = data.get("by_account", {}).get(str(account_id), [])
        # URLが取得済みのものだけ対象
        valid = [p for p in progs if p.get("url") and not p["url"].startswith("__pending__")]
        return valid[0] if valid else None
    except Exception:
        return None

# アカウントごとのペルソナ定義
PERSONAS = {
    1: {
        "name": "たくみ（28歳・都内IT企業勤務）",
        "profile": "新卒でSIerに入って5年目。残業多くて副業でChatGPTを使い始めたら月8万稼げるようになった。彼女なし・趣味はゲームと筋トレ。",
        "tone": "友達に話すような口語体。「〜なんですよね」「〜だったりします」「正直に言うと」をよく使う。たまに「まじで」「ぶっちゃけ」も入れる。失敗談を正直に書く。",
        "quirks": "月収の具体的な数字をよく出す。スクショや実例を「貼っときます」と言う。「最初はこれ全然うまくいかなくて」という失敗から入るのが癖。",
    },
    2: {
        "name": "ゆうき（26歳・地方在住・手取り22万の会社員）",
        "profile": "地方の中小企業勤め。奨学金返済中で手取り少なくて節約を始めたら年100万貯金できるようになった。投資は新NISAから始めたばかり。",
        "tone": "ていねいだけど堅くない。「〜してみたんですが」「意外と〜でした」をよく使う。共感を大事にする。数字を具体的に出す（例: 月23,000円削れた）。",
        "quirks": "「地方民でもできた」という視点を入れる。失敗したこと（無駄遣いしてた過去など）を正直に書く。家計簿の実数値をよく出す。",
    },
    3: {
        "name": "けんじ（31歳・転職経験3回）",
        "profile": "新卒の会社を2年で辞めて3回転職。最初の転職は失敗したけど2回目で年収150万アップ。今は転職の経験を活かして記事を書いてる。",
        "tone": "リアルで具体的。「これ実際に使った一言なんですが」「面接官にこう言ったら雰囲気変わった」みたいな実体験ベース。「〜と思います」は使わず断言する。",
        "quirks": "失敗した転職の話を必ず入れる。「ぼくの失敗談から先に言います」という入り方が多い。年収の具体的な数字を出す。",
    },
}


def generate_article(research: dict) -> dict:
    account_id = research.get("account_id", 1)
    persona = PERSONAS.get(account_id, PERSONAS[1])
    kindle_book = research.get("kindle_book")

    if kindle_book:
        kindle_cta_instruction = f"""

## Kindle本の紹介（必須・有料部分の最後に追加）
この記事と関連するKindle本が出版されています。
有料部分の締めくくりに、自然な流れで以下の情報を紹介してください。
キャラクターとして「自分が読んで参考になった本」として紹介する形で。

本のタイトル:「{kindle_book['title']}」（著者: D.ryu）
内容: {kindle_book['description']}

紹介文の例:
「この内容をもっと体系的に学びたい人には、『{kindle_book['title']}』がおすすめです。
Kindleで読めるので、ぜひチェックしてみてください。」"""
    else:
        kindle_cta_instruction = ""

    # 無料部分末尾CTA（アカウントテーマに合わせる）
    FREE_CTAS = {
        1: "🤖 ChatGPT副業の最新ネタ・使えるプロンプトを毎日配信中 → https://t.me/+yUiqVJi2uNFiOTA1",
        2: "📊 AIが毎日6つのボットの投資シグナルを無料配信中 → https://t.me/+yUiqVJi2uNFiOTA1",
        3: "💼 転職・年収交渉のリアルな情報を毎日配信中 → https://t.me/+yUiqVJi2uNFiOTA1",
    }
    free_cta = FREE_CTAS.get(account_id, FREE_CTAS[2])

    # アフィリエイトリンクCTA
    affiliate = load_best_affiliate(account_id)
    if affiliate:
        affiliate_cta_instruction = f"""

## アフィリエイト案件の紹介（必須・有料部分の末尾に自然に挿入）
記事の内容に関連するサービスを、キャラクターとして「自分が実際に使っている・試した」という形で紹介してください。
宣伝臭くならないように。読者の悩みの解決策として自然に出す。

サービス名: {affiliate['name']}
リンク: {affiliate['url']}
報酬情報（読者には見せない、あなたの参考情報）: {affiliate['commission_text']}

紹介文の例:
「ぼく自身はこれを使って〇〇できました。無料から始められるので試してみてください。→ {affiliate['url']}」
（キャラクターの言葉でアレンジしてOK。URLはそのまま入れること）"""
    else:
        affiliate_cta_instruction = ""

    prompt = f"""あなたは以下のキャラクターとして、自分の実体験をベースにnoteの有料記事を書いてください。

## あなたのキャラクター
名前・属性: {persona['name']}
プロフィール: {persona['profile']}
文体・口癖: {persona['tone']}
書き方の癖: {persona['quirks']}

## 記事仕様
- タイトル: {research['title']}
- テーマ: {research['topic']}
- ターゲット読者: {research['target']}
- 切り口: {research['angle']}
- 価格: ¥{research['price']}

## 重要ルール（必ず守る）
- AIが書いたと思われない文体にする
- 「〜しましょう」「〜することが大切です」は禁止
- 必ず失敗談か「最初うまくいかなかった話」を入れる
- 具体的な数字・日付・場面を入れる（例: 「先月の水曜日に試したら」）
- 箇条書きだけにしない。感情・背景・ツッコミを入れる

## 無料部分（200〜300字）
キャラクターとして読者の悩みに共感する書き出し。
「続きに全部書きました。」で締める。
末尾に必ず以下を追加する（文言そのまま）:
「{free_cta}」

## 有料部分（2500〜4000字）
実体験ベースで手順・ノウハウを書く。
失敗談→気づき→解決策の流れ。
最後は「まとめ」と「次にやること」で締める。
{kindle_cta_instruction}{affiliate_cta_instruction}

## 出力形式（以下のフォーマットを厳守。JSONは使わない）

TITLE: {research['title']}
{SEPARATOR}
FREE_BODY:
（ここに無料部分のテキストを書く）
{SEPARATOR}
PAID_BODY:
（ここに有料部分のテキストを書く）
{SEPARATOR}
TAGS: タグ1,タグ2,タグ3,タグ4,タグ5
"""
    for attempt in range(5):
        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config={"temperature": 0.8}
            )
            text = response.text.strip()
            return _parse_response(text, research)
        except Exception as e:
            err = str(e)
            if attempt < 4 and ("429" in err or "503" in err or "UNAVAILABLE" in err or "RESOURCE_EXHAUSTED" in err):
                wait = 60 * (attempt + 1)
                print(f"  [WAIT] APIエラー({err[:60]})。{wait}秒後にリトライ({attempt+1}/4)...")
                time.sleep(wait)
            else:
                raise


def _parse_response(text: str, research: dict) -> dict:
    parts = text.split(SEPARATOR)

    def extract(prefix: str, block: str) -> str:
        lines = block.strip().splitlines()
        # prefixの行を除いて残りを返す
        result = []
        skip_first = True
        for line in lines:
            if skip_first and line.strip().startswith(prefix):
                skip_first = False
                rest = line[len(prefix):].strip()
                if rest:
                    result.append(rest)
                continue
            result.append(line)
        return "\n".join(result).strip()

    title     = research["title"]
    free_body = ""
    paid_body = ""
    tags      = research.get("keywords", ["AI副業", "副業", "ChatGPT"])

    for part in parts:
        p = part.strip()
        if p.startswith("TITLE:"):
            title = p[len("TITLE:"):].strip()
        elif "FREE_BODY:" in p:
            free_body = extract("FREE_BODY:", p)
        elif "PAID_BODY:" in p:
            paid_body = extract("PAID_BODY:", p)
        elif "TAGS:" in p:
            line = [l for l in p.splitlines() if "TAGS:" in l]
            if line:
                tags = [t.strip() for t in line[0].replace("TAGS:", "").split(",")][:5]

    if not free_body or not paid_body:
        raise ValueError(f"記事パースに失敗しました。出力:\n{text[:500]}")

    return {
        "title":     title,
        "free_body": free_body,
        "paid_body": paid_body,
        "tags":      tags,
    }


if __name__ == "__main__":
    sample = {
        "topic": "ChatGPT副業",
        "title": "ChatGPTで月3万の副収入を作った方法",
        "target": "副業を始めたい会社員",
        "angle": "初期費用ゼロ・スキル不要",
        "price": 500,
        "keywords": ["ChatGPT副業", "AI副業", "副業初心者"]
    }
    result = generate_article(sample)
    print(f"タイトル: {result['title']}")
    print(f"無料部分: {len(result['free_body'])}字")
    print(f"有料部分: {len(result['paid_body'])}字")
    print(f"タグ: {result['tags']}")
