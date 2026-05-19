---
company: saas-dev
updated: 2026-05-19
---

## 稼働中プロジェクト
- 投資ボット6本: SHORT/MEDIUM/LONG/MACRO/ATTACK/VOLT（GitHub Actions 4時間ごと/毎日/毎週）
- 楽天ROOM自動投稿: 1日4回（07/12/18/22時JST）・**現在セッション切れ中**・要ローカルauth更新
- Kindle KDP: EPUB自動生成（日曜・水曜 JST7時）累計6冊・手動アップロード待ち
- Redbubble: MidnightTorii 手動アップロード（next_index=4、残16件）
- ダッシュボード: docs/index.html（毎日JST7時自動生成）+ Flask app

## Gumroad（ventures-auto 傘下）
- **9商品公開済み** / 売上 $0 / 全商品アフィリエイト25%設定済み
- 商品一覧: Procreate Assets($37) / DesignGenie($37) / AI Content Boost($39) / Procreate AI($39) / Procreate Aid($39) / Viral Content($39) / ADHD Unlocked($39) / Etsy Seller Boost($39) / Etsy Success Boost($39)

## Dev.to Publisher（ventures-auto 傘下）
- 2x/day化完了（JST 11:00 + 20:00）
- ジャンル別Gumroad CTA設定済み

## 重要パス
- 投資ボット: `saas-dev/projects/auto-invest/`
- 楽天ROOM: `saas-dev/projects/rakuten-room/`（auth更新: `.\update_auth.ps1`）
- Kindle KDP: `saas-dev/projects/kindle-kdp/output/` (6冊)
- FudoText: `saas-dev/projects/fudosan-copy/`
- コールドメール: `saas-dev/projects/fudosan-copy/outreach/`

## FudoText 顧客獲得（進行中）
- LP: `docs/fudotext.html`（GitHub Pages公開済み）
- SEO記事: `docs/fudotext/` 8本（週次自動追加・毎週月曜）
- コールドメールパイプライン: `outreach/` フォルダ
  - leads.csv: 26件収集済み（Brave Search API使用）
  - 送信済み: **7件（誤送信・パーソナライズなし・署名「ryuu」）**
  - draft待機: 18件（未送信・確認待ち）
  - .env設定済み: GMAIL_ADDRESS / GMAIL_APP_PASSWORD / BRAVE_API_KEY
- **次のアクション**: テストメール表示確認 → leads.csvクリーンアップ → 本番送信

## 現在の課題
- FudoText: メール文字化け疑い・Gemini 429でパーソナライズ失敗中
- FudoText: leads.csvに不適切リード混在（求人サイト・メール営業会社）
- 楽天ROOM: セッション切れ（ローカルで`.\update_auth.ps1`必須）
- KDP: 6冊のEPUBが未アップロード
- Gumroad売上 $0

## ユニバース（ATTACK/VOLT/MEDIUM）
BTC-USD, ETH-USD, SOL-USD, NVDA, AMD, TSLA, META, PLTR, COIN, MSTR, ARM, AVGO

## 直近の決定
- X(Twitter) API: 有料のため永久廃止（2026-05-19）
- note.com: FudoText集客には不向き（ジャンル不一致）廃止（2026-05-19）
- コールドメール: Brave Search API（$5無料枠）でリード収集（2026-05-19）
- 本名「真柄龍聖」をメール署名に使用（特定電子メール法対応・2026-05-19）
- 本物企業への送信はメール品質確認後のみ（2026-05-19）
- FudoText SEO記事8本公開・週次自動追加（2026-05-19）
