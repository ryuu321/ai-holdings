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
- URL: `https://ryuumg.gumroad.com/l/{permalink}`
- 生成スケジュール: 月水金 JST9時（gumroad-generate.yml）

## Dev.to / Medium Publisher（ventures-auto 傘下）
- 9記事投稿済み・**2x/day化完了**（JST 11:00 + 20:00）
- ジャンル別Gumroad CTA: Personal Finance→ndtsjv / Career→akikab / AI→akikab
- Personal Finance URL要修正: `https://ryuumg.gumroad.com/l/ndtsjv`（未反映）

## Reddit（traffic）
- `reddit-daily.yml` デプロイ済み（JST 11:00 毎日）
- REDDIT_SESSION_B64 / PINTEREST_SESSION_B64 → GitHub Secrets 登録済み
- **Reddit from GitHub Actions は不可**（Azure VM IPがブロック対象）

## 重要パス
- 投資ボット: `saas-dev/projects/auto-invest/`
- 楽天ROOM: `saas-dev/projects/rakuten-room/`
  - auth更新コマンド: `.\update_auth.ps1`（毎回ローカル実行必須）
  - 状態: `data/daily_count.json`
- Kindle KDP: `saas-dev/projects/kindle-kdp/output/` (6冊)
- Gumroad: `saas-dev/projects/gumroad/pipeline.py`
- Dev.to: `saas-dev/projects/ventures/medium_publisher/`
- Traffic: `saas-dev/projects/traffic/`

## 現在の課題
- 楽天ROOM: セッション切れ（Akamai E01_008でCIからログイン不可）→ ローカルで`.\update_auth.ps1`必須
- KDP: 6冊のEPUBが未アップロード（AmazonもCIからブロック）→ 手動アップロード
- Gumroad売上 $0: コンテンツはあるがトラフィックがない

## ユニバース（ATTACK/VOLT/MEDIUM）
BTC-USD, ETH-USD, SOL-USD, NVDA, AMD, TSLA, META, PLTR, COIN, MSTR, ARM, AVGO

## FudoText（新規・商用化完了 2026-05-19）
- パス: `saas-dev/projects/fudosan-copy/`
- URL: Streamlit Cloud（デプロイ済み）
- モデル: gemini-3.1-flash-lite（500 RPD無料枠・専用APIキー）
- 機能: 物件説明文AI生成（SUUMO/at home/HOMES対応）
- フィードバック: Google Form → Sheets CSV → 週次Gemini分析 → PR自動作成
- 次のアクション: LP作成 → 顧客獲得（Twitter DM・note記事）

## 直近の決定
- Reddit from CI は永久不可と確定（2026-05-15）
- Dev.to 2x/day化（2026-05-15）
- Gumroadパーソナルファイナンスニッチ5種追加（2026-05-15）
- KDP著者名D.ryuに統一
- Redbubble自動化は永久廃止（Cloudflare Turnstile）
- SEOガイドページ45本公開（26→45、2026-05-17）
- product_articles 80トピック完成（42→80、2026-05-17）
- コンテキスト上限前に自動/end実行ルール追加（2026-05-17）
- FudoText 商用化GO・LP作成が次のアクション（2026-05-19）
