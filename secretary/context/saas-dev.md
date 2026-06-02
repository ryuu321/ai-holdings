---
company: saas-dev
updated: 2026-06-02
---

## 稼働中プロジェクト
- 投資ボット6本: SHORT/MEDIUM/LONG/MACRO/ATTACK/VOLT（GitHub Actions 4時間ごと/毎日/毎週）
- Kindle KDP: EPUB自動生成（日曜・水曜 JST7時）累計6冊・手動アップロード待ち
- Redbubble: MidnightTorii 手動アップロード（next_index=4、残16件）

## TextSeries（最重要事業）

### 製品数・インフラ
- **103製品** Cloud Run デプロイ済み
- URL: `https://{slug}-cup7okvfwq-an.a.run.app`
- Supabase: 全製品共通（REST API直接呼び出し）

### 全自動営業フロー（人手ゼロ）
1. **コールドメール送信**（平日11:30 JST）← **2026-06-02 パイプライン修正完了・初回実送信待ち**
2. デモ後フォローアップ（7日後）
3. Stripe課金検知（毎時）→ UUIDコード自動生成 → メール送信
4. フォローアップシーケンス（7日後）

### GTM リード収集
- SharoText: tokyosr.jp（社労士）
- CareText/TokuText/DayText等: MHLW 介護サービス API（サービスコード別）
- KenText + 建設系16製品: MLIT 建設業 DB（工種コード別）
- GyoText: gyosei.or.jp（Playwright）
- TaxText: freee 認定アドバイザーディレクトリ
- AfterText: WAM Net（code 615/614）
- IinText: MHLW 医療機能情報公表
- 残り75製品: Yahoo Japan/DDG 検索スクレイパー

### GTMパイプライン修正履歴（2026-06-02 完了）
- pipeline.py _ROOT パスバグ修正（3段→4段、89製品）
- ICP閾値修正（auto_approve 70→50・review 50→30、100製品）
- 89製品メールテンプレ正規構造に再構築（TextSeries/配信停止/住所/真柄龍聖）
- qualify_leads.py: hint_keywords追加・士業/医療 法人種別大幅追加
- generate_emails.py: SEOページタイトル保護機能（Step2.5・「」括弧・_TRAIL_TYPES拡張）
- bengoshitext dry-run確認済み（3-4件承認・会社名クリーン抽出）

### note TextSeries ローテーション（2026-06-02 構築）
- textseries-note-generate: **JST 0:00** 毎日5件生成（深夜専用・GTMと時間分離）
- textseries-note-post: **JST 7:00** 毎日2件投稿（generate=false）
- 103製品 ÷ 5件/日 = 約21日で1周、全生成後は自動スキップ
- 現状: sharotext_article.md のみ生成済み・投稿済み

### Supabase テーブル
- 各製品: `{slug}_trials`, `{slug}_codes`, `{slug}_history`, `{slug}_feedback`
- 共通: `textseries_followup_log`

### 課題
- **FudoText 8社返信待ち（2026-05-19送信・14日以上経過）← 最優先**
- KDP手動アップロード6冊待ち
- 楽天ROOM: AkamaiブロックでCIログイン不可→ローカルupdate_auth.ps1実行必要

### 製品品質方針
- PMFシグナル（フィードバック・課金）が出た製品に集中
- 103製品全部を事前改修しない
