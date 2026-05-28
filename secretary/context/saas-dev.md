---
company: saas-dev
updated: 2026-05-27
---

## 稼働中プロジェクト
- 投資ボット6本: SHORT/MEDIUM/LONG/MACRO/ATTACK/VOLT（GitHub Actions 4時間ごと/毎日/毎週）
- 楽天ROOM: **撤退決定（2026-05-27）**
- Kindle KDP: EPUB自動生成（日曜・水曜 JST7時）累計6冊・手動アップロード待ち
- Redbubble: MidnightTorii 手動アップロード（next_index=4、残16件）

## TextSeries（最重要事業）

### 製品数・インフラ
- **103製品** Cloud Run デプロイ中（2026-05-27時点: 59済み・44バックグラウンドデプロイ中）
- URL: `https://{slug}-cup7okvfwq-an.a.run.app`
- HOSTING_PROJECT: `textseries-tokutext-api`（課金有効）
- GCP pool: pool-001〜010（各10製品）+ individual（6製品）
- Supabase: 全製品共通（REST API直接呼び出し）

### 全自動営業フロー（人手ゼロ）
1. コールドメール送信（平日11:30 JST）← **現在0件送信中**（会社名スコアリング問題）
2. デモ後フォローアップ（平日10/12/14/16時 JST）← **2026-05-27追加**
3. Stripe課金検知（毎時）→ UUIDコード自動生成 → メール送信
4. フォローアップシーケンス（7日後）

### 営業自動化の既知の穴
- コールドメールが0件: 会社名が取れずスコア70未達（意図的に放置中・Bアプローチ）
- デモ後フォローアップは正常動作予定

### Supabase テーブル
- 各製品: `{slug}_trials`, `{slug}_codes`, `{slug}_history`, `{slug}_feedback`
- 共通: `textseries_followup_log`（2026-05-27作成: slug/email/sent_at）

### 課題
- FUDOTEXT_PAT未登録: apply_pdca.pyが動かない（手動5分）
- FudoText 8社返信待ち（2026-05-19送信・8日経過）
- KDP手動アップロード6冊待ち

### 製品品質方針
- 103製品全部を深掘りするのでなく、PMFシグナル（フィードバック・課金）が出た製品に集中
- 業界知識は法令・専門用語レベルで入っている（十分なMVP）
- フィードバックボタン（👍👎）がSupabaseに蓄積される仕組みあり
