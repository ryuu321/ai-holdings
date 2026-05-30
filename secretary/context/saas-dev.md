---
company: saas-dev
updated: 2026-05-30
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

### GTM リード収集（2026-05-30 本格化）
- **Brave API 完全廃止** → 製品別専用スクレイパーに切り替え完了
- SharoText: tokyosr.jp（291リード・26件送信・63件ドラフト待機）
- CareText: MHLW介護サービス API（kaigokensaku.mhlw.go.jp）
- KenText + 建設系16製品: MLIT 建設業 DB（etsuran2.mlit.go.jp）工種コード別
- TokuText/KangoText/DayText等: MHLW 介護 DB（サービスコード別）
- GyoText: gyosei.or.jp を Playwright で突破（GitHub Actions 上）
- TaxText: freee 認定アドバイザーディレクトリ（DM 歓迎・ToS 問題なし）
- AfterText: WAM Net 障害福祉サービス等情報公表（code 615/614）
- IinText: MHLW 医療機能情報公表 mfis.mhlw.go.jp
- 残り 75 製品: Yahoo Japan/DDG 検索フォールバック
- send_emails.py バグ修正（法人格チェックで全バッチ停止 → 個別 SKIP に修正）

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
