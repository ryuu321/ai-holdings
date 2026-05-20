# AI Holdings — 標準SaaSスタック & 実装パターン集

> `saas-build.md` = プロセス（何をするか）
> このファイル = 実装（どう作るか）
>
> **再利用できるもの**: インフラ・課金・通信レイヤー
> **毎回書くもの**: UIとプロンプト（製品の本質なので当然）

---

## アーキテクチャ決定（変えない）

| レイヤー | 選択肢 | 理由 |
|---------|-------|------|
| UI | Streamlit Cloud | 無料・デプロイ1コマンド |
| AI | Gemini Flash (`gemini-2.0-flash-lite`) | 無料枠500RPD |
| DB | Supabase REST API直呼び | clientライブラリ不使用（互換問題多発） |
| 課金 | 銀行振込 + アクセスコード | Stripe申告書不要・個人でも即開始 |
| メール | Gmail SMTP + アプリパスワード | 無料・実績あり |
| リード収集 | Brave Search API | 無料$5枠 |
| LP | GitHub Pages (`/docs/`) | 無料・CDN自動 |

---

## 再利用できるもの vs 毎回書くもの

```
saas-dev/projects/{name}/
├── app.py              ← 毎回書く（UIは製品ごとに違う）
├── prompt.py           ← 毎回書く（プロンプトは製品の本質）
│
├── db.py               ← ほぼコピー（接続・認証・課金ロジック）
├── gen_access_code.py  ← ほぼコピー（文言だけ変える）
├── requirements.txt    ← コピー（追加依存があれば足す）
│
└── outreach/           ← shared/gtm/ を使い回す
    ├── fetch_leads.py  ← dotenv追加のみでコピー
    ├── follow_up.py    ← コピー
    ├── check_replies.py← コピー
    └── pipeline.py     ← コピー
```

---

## 再利用パターン集

### db.py — Supabase REST API（ほぼコピー）

```python
import os, json, urllib.request, urllib.error

def _headers():
    key = os.environ["SUPABASE_ANON_KEY"].strip()
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

def _url(table, query=""):
    base = os.environ["SUPABASE_URL"].strip().rstrip("/")
    if base.endswith("/rest/v1"):   # Secrets貼り付け時に /rest/v1 が混入する場合がある
        base = base[:-len("/rest/v1")]
    return f"{base}/rest/v1/{table}" + (f"?{query}" if query else "")

def _req(method, table, query="", body=None):
    req = urllib.request.Request(
        _url(table, query),
        data=json.dumps(body).encode() if body else None,
        headers=_headers(),
        method=method,
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def get_or_create_user(email: str) -> dict:
    rows = _req("GET", "trials", f"email=eq.{email}&select=email,count,plan")
    if rows:
        return rows[0]
    _req("POST", "trials", body={"email": email, "count": 0, "plan": "free"})
    return {"email": email, "count": 0, "plan": "free"}

def increment_count(email: str) -> int:
    rows = _req("GET", "trials", f"email=eq.{email}&select=count")
    new_count = (rows[0]["count"] if rows else 0) + 1
    _req("PATCH", "trials", f"email=eq.{email}", {"count": new_count})
    return new_count

def set_plan(email: str, plan: str):
    _req("PATCH", "trials", f"email=eq.{email}", {"plan": plan, "count": 0})

def validate_code(code: str):
    rows = _req("GET", "codes", f"code=eq.{code}&active=eq.true&select=plan")
    if not rows:
        return None
    _req("PATCH", "codes", f"code=eq.{code}", {"active": False})
    return rows[0]["plan"]

def issue_code(company: str, plan: str) -> str:
    rows = _req("POST", "codes", body={"company": company, "plan": plan, "active": True})
    return rows[0]["code"]
```

---

### app.py の課金レイヤー（パターンだけ抽出・UIは書かない）

UIは製品ごとに全く異なる。ただし**課金レイヤーの制御フローは毎回同じ**なので構造だけ示す。

```python
# ─── 課金レイヤー（共通・変えない）───────────────────────────────
FREE_LIMIT = 5
PLAN_LIMITS = {"standard": 50, "pro": 200}

# step1: メールゲート（DBがなければスキップ）
if not st.session_state.get("email"):
    # ... メール入力UIを書く（製品固有）
    pass

# step2: 上限チェック + アップグレード
limit = PLAN_LIMITS.get(st.session_state.get("plan", "free"), FREE_LIMIT)
if st.session_state.get("count", 0) >= limit:
    # ... アクセスコード入力UIを書く（1〜2行で済む）
    st.stop()

# ─── 製品固有レイヤー（ここから下を毎回書く）────────────────────
# ... 入力フォーム・生成ボタン・結果表示
```

> session_state のキー名 (`email`, `count`, `plan`) だけ統一すれば課金ロジックは使い回せる。

---

### prompt.py の骨格（バックオフだけ再利用・プロンプトは毎回書く）

```python
import os, json, time, urllib.request, urllib.error

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")

def call_gemini(prompt: str, max_tokens: int = 800) -> dict:
    """戻り値: {"ok": True, "text": "..."} or {"ok": False, "error": "..."}"""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={api_key}"
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }).encode()

    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            return {"ok": True, "text": data["candidates"][0]["content"]["parts"][0]["text"].strip()}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** (attempt + 1))   # 2s → 4s → 8s
                continue
            return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "Gemini 429 上限。しばらく待ってから再実行してください。"}

# ─── 製品固有（ここを毎回書く）──────────────────────────────────
def generate_property_description(inputs: dict) -> dict:
    prompt = f"""..."""   # 製品の本質
    return call_gemini(prompt, max_tokens=600)
```

---

### gen_access_code.py（文言だけ変えてコピー）

```python
"""
python gen_access_code.py --company "会社名" --plan standard --to email@example.com [--dry-run]
"""
import argparse, smtplib, os
from email.mime.text import MIMEText
from dotenv import load_dotenv
load_dotenv()
from db import issue_code

PRODUCT_NAME = "FudoText"   # ← 変える
APP_URL = os.environ.get("APP_URL", "")

BODY = """{company} 様

{product}をご契約いただき、誠にありがとうございます。

■ アクセスコード: {code}
■ プラン: {plan}

アプリにアクセスし、コードを入力してください:
{url}

ご不明な点はご返信ください。

真柄 龍聖
"""

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--company", required=True)
    p.add_argument("--plan", choices=["standard", "pro"], required=True)
    p.add_argument("--to", required=True)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    code = issue_code(args.company, args.plan)
    body = BODY.format(company=args.company, product=PRODUCT_NAME,
                       code=code, plan=args.plan, url=APP_URL)
    if args.dry_run:
        print(f"[DRY-RUN]\nコード: {code}\n{body}")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"【{PRODUCT_NAME}】アクセスコードのご案内"
    msg["From"] = os.environ["GMAIL_ADDRESS"]
    msg["To"] = args.to
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(os.environ["GMAIL_ADDRESS"], os.environ["GMAIL_APP_PASSWORD"])
        s.send_message(msg)
    print(f"送信完了 → {args.to} / コード: {code}")

if __name__ == "__main__":
    main()
```

---

### requirements.txt（コピー・必要なら追加）

```
streamlit
google-genai
python-dotenv
```

`supabase` は入れない。REST API直呼びで代替。

---

### .streamlit/secrets.toml.example（キー名だけ記録）

```toml
GEMINI_API_KEY = ""
SUPABASE_URL = ""        # 末尾に /rest/v1 を付けない
SUPABASE_ANON_KEY = ""
GMAIL_ADDRESS = ""
GMAIL_APP_PASSWORD = ""
APP_URL = ""
```

---

## Supabase 初期SQL（毎回同じ・コピペ）

```sql
CREATE TABLE trials (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  email text UNIQUE NOT NULL,
  count integer DEFAULT 0,
  plan text DEFAULT 'free',
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);
CREATE TABLE codes (
  code text DEFAULT gen_random_uuid() PRIMARY KEY,
  company text,
  plan text,
  active boolean DEFAULT true,
  issued_at timestamptz DEFAULT now()
);
ALTER TABLE trials DISABLE ROW LEVEL SECURITY;
ALTER TABLE codes DISABLE ROW LEVEL SECURITY;
GRANT ALL ON trials TO anon;
GRANT ALL ON codes TO anon;
-- ⚠️ RLS無効 = anon キーで全行読み書き可能。個人利用中は許容範囲。
-- 顧客の個人情報（氏名・住所等）をDBに保存し始めたら即座に RLS を有効化すること。
-- 有効化手順: ENABLE ROW LEVEL SECURITY → CREATE POLICY でユーザーごとのアクセス制御を追加
```

---

## GTM設定テンプレート（shared/gtm/config/{name}.json）

ICPキーワード・スコアリング・件名だけ変えればパイプラインが動く。

**コールドメール法的要件（特定電子メール法）**: 送信前に必ず確認
- `sender_address` が設定されていること（バーチャルオフィス住所）
- `opt_out.csv` が存在し、照合されていること
- 配信停止申し出から2営業日以内に `--add-opt-out` で記録すること

```json
{
  "project": "{name}",
  "product_name": "{ProductName}",
  "app_url": "",
  "lp_url": "",
  "sender_name": "真柄 龍聖",
  "sender_email": "ryuumg03@gmail.com",
  "sender_address": "〒060-0001 北海道札幌市中央区北一条西3丁目3番地33 リープロビル302",
  "daily_send_limit": 30,
  "send_interval_sec": 30,
  "gemini_model": "gemini-2.0-flash-lite",
  "icp": {
    "target_description": "",
    "target_keywords": [],
    "good_domain_suffixes": ["co.jp", "jp"],
    "bad_domain_suffixes": ["gmail.com", "yahoo.co.jp"],
    "exclude_keywords": [
      "求人", "転職", "協会", "組合", "省", "庁",
      "ランキング", "比較", "一覧"
    ]
  },
  "scoring": {
    "target_keyword_hit": 30,
    "good_domain": 20,
    "has_company_type": 20,
    "bad_domain_penalty": -20,
    "exclude_keyword_penalty": -50,
    "auto_approve_threshold": 70,
    "review_threshold": 50
  },
  "email_template": {
    "subject": "",
    "personalize_prompt": "",
    "fallback_opening": ""
  }
}
```

---

## LP構造（docs/{name}.html に必須のセクション）

```
1. ヒーロー        — 「〇〇が××秒でできる」（数字必須）
2. Before/After    — 今の課題 → ツール後の状態
3. 機能一覧        — 3〜5項目
4. 料金            — 無料 / スタンダード / プロ
5. CTA             — アプリへのリンク
6. 特定商取引法    — 有償の場合は必須（住所は実記載。「請求があり次第」不可）
7. プライバシーポリシー — メールアドレス取得する場合は必須
8. フッター        — © + 特商法/PPへのアンカーリンク
```

### LP 法的セクション HTML テンプレート（コピー → 住所・価格・日付だけ変える）

```html
<!-- 特定商取引法に基づく表記 -->
<section id="tokushoho" class="py-16 px-6 bg-gray-50">
  <div class="max-w-2xl mx-auto">
    <h2 class="text-xl font-bold mb-8 text-gray-700">特定商取引法に基づく表記</h2>
    <table class="w-full text-sm text-gray-600 border-collapse">
      <tbody>
        <tr class="border-b border-gray-200"><td class="py-3 pr-6 font-medium text-gray-700 w-36">販売事業者</td><td class="py-3">真柄 龍聖</td></tr>
        <tr class="border-b border-gray-200"><td class="py-3 pr-6 font-medium text-gray-700">所在地</td><td class="py-3">〒060-0001 北海道札幌市中央区北一条西3丁目3番地33 リープロビル302</td></tr>
        <tr class="border-b border-gray-200"><td class="py-3 pr-6 font-medium text-gray-700">電話番号</td><td class="py-3">請求があり次第、遅滞なく開示します</td></tr>
        <tr class="border-b border-gray-200"><td class="py-3 pr-6 font-medium text-gray-700">メール</td><td class="py-3"><a href="mailto:ryuumg03@gmail.com" class="underline">ryuumg03@gmail.com</a></td></tr>
        <tr class="border-b border-gray-200"><td class="py-3 pr-6 font-medium text-gray-700">販売価格</td><td class="py-3">無料プラン：無料 / スタンダードプラン：要相談 / プロプラン：要相談（アクセスコード発行方式）</td></tr>
        <tr class="border-b border-gray-200"><td class="py-3 pr-6 font-medium text-gray-700">支払方法</td><td class="py-3">銀行振込（振込先は契約時にご案内）</td></tr>
        <tr class="border-b border-gray-200"><td class="py-3 pr-6 font-medium text-gray-700">提供時期</td><td class="py-3">入金確認後、アクセスコードをメールにてお送りします（通常1営業日以内）</td></tr>
        <tr class="border-b border-gray-200"><td class="py-3 pr-6 font-medium text-gray-700">返品・キャンセル</td><td class="py-3">デジタルコンテンツの性質上、アクセスコード発行後の返品・返金はお受けできません</td></tr>
      </tbody>
    </table>
  </div>
</section>

<!-- プライバシーポリシー -->
<section id="privacy" class="py-16 px-6">
  <div class="max-w-2xl mx-auto">
    <h2 class="text-xl font-bold mb-8 text-gray-700">プライバシーポリシー</h2>
    <div class="space-y-6 text-sm text-gray-600">
      <div>
        <h3 class="font-semibold text-gray-700 mb-2">収集する情報</h3>
        <p>本サービスへの問い合わせ・返信メールにより、メールアドレスおよびメール本文に含まれる情報を取得する場合があります。アプリ利用時に入力された情報は一時処理のみに使用し、サーバーに保存しません。</p>
      </div>
      <div>
        <h3 class="font-semibold text-gray-700 mb-2">外部サービスへの送信</h3>
        <p>入力された情報はAI生成のためGoogle Gemini APIに送信されます。Googleのプライバシーポリシーが適用されます。</p>
      </div>
      <div>
        <h3 class="font-semibold text-gray-700 mb-2">利用目的</h3>
        <p>取得した情報は、お問い合わせへの回答、サービス改善、および有償プランの契約手続きにのみ使用します。</p>
      </div>
      <div>
        <h3 class="font-semibold text-gray-700 mb-2">第三者への提供</h3>
        <p>法令に基づく場合を除き、取得した個人情報を第三者へ提供することはありません。</p>
      </div>
      <div>
        <h3 class="font-semibold text-gray-700 mb-2">お問い合わせ・開示請求</h3>
        <p>個人情報の開示・訂正・削除のご請求は <a href="mailto:ryuumg03@gmail.com" class="underline">ryuumg03@gmail.com</a> までご連絡ください。</p>
      </div>
      <p class="text-xs text-gray-400">制定日：YYYY年MM月DD日　真柄 龍聖</p>
    </div>
  </div>
</section>

<!-- フッター -->
<footer class="py-8 px-6 text-center text-gray-400 text-sm">
  <p>© 2026 {ProductName} &nbsp;|&nbsp;
    <a href="#tokushoho" class="underline hover:text-gray-600">特定商取引法</a>
    &nbsp;|&nbsp;
    <a href="#privacy" class="underline hover:text-gray-600">プライバシーポリシー</a>
  </p>
  <p class="mt-2 text-xs text-gray-300">AIが生成したコンテンツです。掲載前に必ず内容をご確認ください。</p>
</footer>
```

---

## 落とし穴（実戦記録）

| 症状 | 原因 | 解決策 |
|-----|------|--------|
| Supabase 404 | URLに `/rest/v1` 二重付与 | `_url()` の末尾チェック |
| Secrets読めない | スマートクォート混入 | キーボードで直接入力 |
| Gemini無応答 | 429レート制限 | バックオフ 2→4→8秒 |
| メール送信失敗 | アプリパスワード未設定 | Google > 2段階認証 → アプリパスワード |
| コールドメール深夜送信 | 時間帯チェックなし | JST9-18チェック実装済み（send_emails.py） |
| 会社名がページタイトル | スクレイピング由来 | `--dry-run` で目視確認必須 |
| LP住所が「請求があり次第」 | バーチャルオフィス取得前の暫定表記 | 住所取得後は即実記載に変更（特商法は住所があるなら開示義務） |
| 配信停止申し出を放置 | opt_out管理なし | 即日 `--add-opt-out` 実行。2営業日以内が法的義務 |
| AIが景品表示法違反表現を生成 | プロンプトに禁止ワード指定なし | プロンプトに「最大級表現（最良・最高・一番等）は使用禁止」を明記 |
