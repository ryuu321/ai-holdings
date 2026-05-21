# B2B SaaS 即収益化プレイブック

アイデアから購入・解約まで全自動で回す再現可能なフレームワーク。
FudoText（不動産向け説明文AI）で実証済み。

---

## 前提条件・コスト

| インフラ | 費用 |
|---------|------|
| Streamlit Cloud | 無料（アプリホスティング） |
| Supabase | 無料枠（DB + Edge Functions） |
| GitHub Actions（public repo） | 無制限無料 |
| Stripe | 決済手数料のみ（月額固定なし） |
| Gmail SMTP | 無料（アプリパスワード） |
| Gemini API | 無料枠 |

**初期投資ゼロ・売れた分だけコストが発生する構造。**

---

## Phase 1: プロダクト設計（1日）

### ICP（理想顧客）を1行で定義する
```
「[職種] が [繰り返す作業] を [時間・コスト] 削減できる」
例: 不動産仲介担当者が物件説明文作成を1件5分→30秒に削減できる
```

### 料金設計
- 無料枠: 5件（試せる量・依存させる量）
- Standard: ¥8,980/月（月50件）
- Pro: ¥19,800/月（月200件）
- **価格は「業務1件あたりコスト × 月件数」で逆算**

### データロック設計
- 使えば使うほど履歴・習慣が蓄積する仕組みを入れる
- 乗り換えコストが上がる＝チャーンが下がる

---

## Phase 2: スタック構築（2〜3日）

### アプリ（Streamlit）
```python
# 最小構成
st.text_input("メールアドレス")   # ユーザー識別
# 無料枠カウント → 上限でCTAを表示
# コード入力欄（上限到達後に表示）
# Stripe決済リンクボタン
```

### データベース（Supabase）
```sql
-- 3テーブル構成
trials (email, count, month)          -- 無料枠管理
codes (code UUID, company, plan, active)  -- アクセスコード
generation_history (email, input, output)  -- 使用履歴（ロック）

-- RLS必須: service_role keyでのみ書き込み可
```

### 環境変数（.env / Streamlit secrets）
```
GEMINI_API_KEY
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_KEY   # ← RLS bypass用
STRIPE_STANDARD_URL
STRIPE_PRO_URL
GMAIL_ADDRESS
GMAIL_APP_PASSWORD
SENDER_ADDRESS         # 特定電子メール法用
```

---

## Phase 3: 決済・コード発行の自動化（1日）

### Stripe設定
1. Payment Links を「定期購読（月額）」で作成（Standard / Pro）
2. Developers → Webhooks → エンドポイント登録:
   - URL: `https://{project}.supabase.co/functions/v1/stripe-webhook`
   - イベント: `checkout.session.completed` / `customer.subscription.deleted` / `invoice.payment_failed`

### Supabase Edge Function: stripe-webhook
```
checkout.session.completed  → codesテーブルにUUID発行 → GitHub Actions起動
customer.subscription.deleted → codes.active = false
invoice.payment_failed（最終失敗時）→ codes.active = false
```

### GitHub Actions: send-code
```yaml
on:
  workflow_dispatch:
    inputs: [to_email, plan, code]
# Gmail SMTPでアクセスコードをメール送信
# ai-holdingsのpublic repoに置く（無制限無料）
```

### Supabase Edge Functionシークレット設定
```bash
npx supabase secrets set --project-ref {ref} \
  STRIPE_SECRET_KEY="sk_live_..." \
  STRIPE_WEBHOOK_SECRET="whsec_..." \
  GITHUB_TOKEN="ghp_..."
# SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY はデフォルトで注入済み
```

---

## Phase 4: 集客自動化（1〜2日）

### リード取得
- 業界固有の公的データベースを使う（MLIT、法人番号DB等）
- Brave Search APIでウェブ検索補完
- ICP採点（スコアリング）で精度向上

### メール生成
- Gemini APIでパーソナライズ（会社名ベース）
- 特定電子メール法必須項目: 送信者名・住所・配信停止文言
- fallback: テンプレートで補完

### 送信
- Gmail SMTP（30件/日上限・JST 9-18時のみ）
- 送信ログ管理（重複防止）
- GitHub Actions（平日自動実行）

---

## Phase 5: 解約管理（0.5日）

### Stripeカスタマーポータル
```bash
# 設定作成
curl -X POST https://api.stripe.com/v1/billing_portal/configurations \
  -u "sk_live_...:" \
  -d "features[subscription_cancel][enabled]=true" \
  -d "features[subscription_cancel][mode]=at_period_end"
```

### Edge Function: portal-session
```
POST /functions/v1/portal-session {"email": "..."}
→ Stripeで顧客検索 → billingPortal.sessions.create → URLを返す
→ アプリの「プラン管理・解約」ボタンから呼び出し
```

---

## チェックリスト（次回展開時）

### プロダクト
- [ ] ICP1行定義
- [ ] 料金3段階（無料/Standard/Pro）
- [ ] データロック機構
- [ ] 特定電子メール法・特商法・プライバシーポリシー

### 技術
- [ ] Streamlitアプリ（メール認証 + 無料枠 + コード解除）
- [ ] Supabase 3テーブル + RLS
- [ ] Stripe Payment Links（月額）
- [ ] stripe-webhook Edge Function
- [ ] send-code GitHub Actions（public repo）
- [ ] portal-session Edge Function
- [ ] Supabaseシークレット設定

### 集客
- [ ] リード収集スクリプト（業界データ源を特定）
- [ ] ICP採点ロジック
- [ ] メールテンプレート（パーソナライズ + 法的文言）
- [ ] 送信自動化（GitHub Actions 平日実行）

### 完成条件
- [ ] Stripe購入 → コードメール自動送信
- [ ] コード入力 → プラン解除
- [ ] 解約 → コード自動無効化
- [ ] カスタマーポータルでセルフ解約可能

---

## 横展開のポイント

**変えるもの（業界ごと）:**
- ICP・プロンプト・テンプレート
- リード収集元（業界固有データベース）
- メール文面

**変えないもの（共通基盤）:**
- Streamlit + Supabase + GitHub Actions + Stripe
- stripe-webhook / portal-session Edge Function
- send-code / fudotext-daily-send ワークフロー構造
- shared/gtm/ パイプライン全体

**目安工数（2回目以降）: 2〜3日で事業インフラ完成**
