# 新製品立ち上げプレイブック

新しい SaaS 製品を立ち上げるときのチェックリスト。
FudoText・SharoText をテンプレートとして設計。

---

## ステップ 0: 命名と準備

- [ ] `PROJECT` 名を決める（英小文字: `kentext` / `sharotext` など）
- [ ] `PRODUCT_NAME` を決める（表示名: `KenText` など）
- [ ] `.env` に新製品用の環境変数枠を追加

---

## ステップ 1: GTM 設定 (config.json)

**ファイル:** `shared/gtm/config/{PROJECT}.json`

必須フィールド:
```json
{
  "project": "{PROJECT}",
  "product_name": "{PRODUCT_NAME}",
  "app_url": "https://{PROJECT}.streamlit.app",
  "lp_url": "https://ryuu321.github.io/ai-holdings/{PROJECT}.html",
  "sender_name": "真柄 龍聖",
  "sender_email": "ryuumg03@gmail.com",
  "sender_address": "〒060-0001 北海道札幌市中央区北一条西3丁目3番地33 リープロビル302",
  "daily_send_limit": 30,
  "send_interval_sec": 30,
  "gemini_model": "gemini-3.1-flash-lite",
  "sent_log": "saas-dev/projects/{PROJECT}/outreach/sent_log.csv",
  "sent_log_gist_filename": "{PROJECT}_sent_log.csv",
  "followup_days": 7,
  "followup_template": "shared/gtm/outreach/templates/{PROJECT}_sequence_2.txt",
  "feedback_csv_env": "{PROJECT_UPPER}_FEEDBACK_CSV_URL",
  "feedback_report_dir": "saas-dev/projects/{PROJECT}/feedback_reports",
  "feedback_prompt_context": "{製品とユーザー像の1〜2行説明}",
  "icp": { ... },
  "scoring": { ... },
  "email_template": { ... }
}
```

スコアリング注意: ターゲットに「株式会社」がない業種（社労士法人など）は
`auto_approve_threshold: 30` に下げる。

---

## ステップ 2: メールテンプレート

- `shared/gtm/outreach/templates/{PROJECT}_sequence_1.txt` (初回コールドメール)
- `shared/gtm/outreach/templates/{PROJECT}_sequence_2.txt` (7日後フォローアップ)

利用可能な変数: `{company_name}` `{sender_name}` `{product_name}` `{app_url}` `{sender_email}` `{sender_address}`

末尾に必ず追記:
```
※本メールは広告・宣伝を目的としております。
※配信停止をご希望の方は、このメールに「配信停止」とご返信ください。
```

---

## ステップ 3: アウトリーチスクリプト

`saas-dev/projects/{PROJECT}/outreach/` に配置:

| ファイル | 内容 |
|---------|------|
| `fetch_leads.py` | Brave API でリード収集（サイト・メール抽出） |
| `send_emails.py` | 一斉送信（fudosan-copy から `--project` だけ変えてコピー） |
| `pipeline.py` | 4ステップ統合実行 |

共有モジュール（追加設定不要で動く）:
- `shared/gtm/leads/qualify_leads.py --project {PROJECT}`
- `shared/gtm/outreach/generate_emails.py --project {PROJECT}`
- `shared/gtm/outreach/check_replies.py --project {PROJECT} --mark`
- `shared/gtm/outreach/follow_up.py --project {PROJECT}`
- `shared/gtm/outreach/analyze_feedback.py --project {PROJECT}`

---

## ステップ 4: GitHub Gist

1. private Gist を作成（初期内容: `email,company_name,subject,sent_at,result` の1行）
2. Gist ID を GitHub Secrets に追加: `{PROJECT_UPPER}_SENT_LOG_GIST_ID`

---

## ステップ 5: GitHub Actions ワークフロー

コピー元 → コピー先の対応（`sharotext` → `{PROJECT}` に置換）:

| ワークフロー | 実行タイミング |
|-------------|--------------|
| `{PROJECT}-daily-send.yml` | 平日 JST 11:00 |
| `{PROJECT}-check-replies.yml` | 平日 JST 10:00 |
| `{PROJECT}-follow-up.yml` | 毎週火曜 JST 10:30 |
| `{PROJECT}-feedback-pdca.yml` | 毎週月曜 JST 5:00 |
| `{PROJECT}-send-code.yml` | 手動（課金後のコード発行） |

---

## ステップ 6: Streamlit アプリ (fudotext repo)

`fudotext/saas-dev/projects/{PROJECT}/` に配置:

| ファイル | 内容 |
|---------|------|
| `app.py` | Streamlit UI（sharotext/app.py をベースに書き換え） |
| `gen.py` | Gemini 生成ロジック（書類種別ごとのプロンプト） |
| `db.py` | Supabase REST（sharotext/db.py をコピーして PROJECT名変更） |
| `requirements.txt` | `streamlit / python-dotenv / python-docx` |

### app.py 課金設計（標準）
```python
FREE_TRIAL_LIMIT = 5
PLAN_LIMITS = {"standard": 50, "pro": 200}
# standard: ¥8,980/月, pro: ¥19,800/月
```

---

## ステップ 7: Supabase DB セットアップ

SQL（`supabase/{PROJECT}_tables.sql`）:
```sql
CREATE TABLE {PROJECT}_trials (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  email text UNIQUE NOT NULL,
  count integer DEFAULT 0,
  plan text,
  created_at timestamptz DEFAULT now()
);
CREATE TABLE {PROJECT}_codes (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  code text UNIQUE NOT NULL,
  plan text NOT NULL,
  active boolean DEFAULT true,
  created_at timestamptz DEFAULT now()
);
CREATE TABLE {PROJECT}_history (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  email text NOT NULL,
  doc_type text,
  company text,
  draft text,
  created_at timestamptz DEFAULT now()
);
-- RLS: anon_all on trials/history, anon_select on codes
```

---

## ステップ 8: Streamlit Cloud デプロイ

1. `https://share.streamlit.io` → New app → fudotext repo
2. Main file: `saas-dev/projects/{PROJECT}/app.py`
3. Secrets:
   ```toml
   GEMINI_API_KEY = "..."
   SUPABASE_URL = "https://xxxxx.supabase.co"
   SUPABASE_ANON_KEY = "..."
   {PROJECT_UPPER}_STRIPE_STANDARD_URL = ""
   {PROJECT_UPPER}_STRIPE_PRO_URL = ""
   ```

---

## ステップ 9: Stripe 課金設定

1. Stripe Dashboard → 製品を作成
   - Standard: ¥8,980/月（recurring）
   - Pro: ¥19,800/月（recurring）
2. 決済リンクを生成してStreamlit Secrets に設定
3. 決済完了後 → GitHub Actions `{PROJECT}-send-code.yml` で手動コード発行

---

## ステップ 10: フィードバック収集設定（PDCA）

1. Google フォームを作成（カラム: `timestamp` `rating` `regen_count` `reasons`）
2. 「回答」→「スプレッドシートにリンク」→「ファイル」→「ウェブに公開（CSV）」でURLを取得
3. GitHub Secrets に追加: `{PROJECT_UPPER}_FEEDBACK_CSV_URL`
4. アプリ内にフォームリンクを設置（例: `st.link_button("フィードバックを送る", form_url)`）

---

## GitHub Secrets チェックリスト

新製品追加時に確認:

- [ ] `{PROJECT_UPPER}_SENT_LOG_GIST_ID`
- [ ] `{PROJECT_UPPER}_FEEDBACK_CSV_URL`
- [ ] `{PROJECT_UPPER}_STRIPE_STANDARD_URL` (Streamlit Secrets)
- [ ] `{PROJECT_UPPER}_STRIPE_PRO_URL` (Streamlit Secrets)
- [ ] 共通シークレット確認: `BRAVE_API_KEY` `GEMINI_API_KEY` `GMAIL_ADDRESS` `GMAIL_APP_PASSWORD` `GIST_TOKEN` `SENDER_ADDRESS` `TELEGRAM_BOT_TOKEN` `TELEGRAM_CHANNEL_ID`
