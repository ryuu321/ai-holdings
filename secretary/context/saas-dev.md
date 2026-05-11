---
company: saas-dev
updated: 2026-05-01
---

## 稼働中プロジェクト
- 投資ボット6本: SHORT/MEDIUM/LONG/MACRO/ATTACK/VOLT（GitHub Actions 4時間ごと/毎日/毎週）
- 楽天ROOM自動投稿: Task Scheduler 1日4回・累計150件・残6624件
- Kindle KDP: EPUB自動生成（日曜・水曜 JST7時）
- Redbubble: MidnightTorii 手動アップロード（next_index=4、残16件）
- ダッシュボード: docs/index.html（毎日JST7時自動生成）+ Flask app

## 重要パス
- 投資ボット: `saas-dev/projects/auto-invest/`
  - 各ボット: `{bot}/main.py` + `{bot}/collector.py`
  - 共有: `shared/summary.py`（summary.json書き出し）
  - データ: `data/portfolio_*.json`, `data/summary.json`
- 楽天ROOM: `saas-dev/projects/rakuten-room/`
  - 状態: `data/daily_count.json`（_total_override=150が正値）
- Redbubble: `saas-dev/projects/redbubble/`
  - デザイン定義: `quotes.py`（20件）
  - 手動アップ用: `upload_data.txt`, `manual_upload_helper.py`
  - 状態: `data/state.json`（next_quote_index=4）
- ダッシュボード: `dashboard/generate.py` → `docs/index.html`

## 現在の課題
- ATTACK/VOLT: 7日サイクルで実トレードなし（ユニバース拡張済み・次サイクル待ち）
- LONG/MACRO: MSFTポジション保有中
- B&H(+35%/年)に対してボットは構造的に負け → ボットの価値はリスク管理(MaxDD 3%台)

## ユニバース（ATTACK/VOLT/MEDIUM）
BTC-USD, ETH-USD, SOL-USD, NVDA, AMD, TSLA, META, PLTR, COIN, MSTR, ARM, AVGO

## 直近の決定
- KDP著者名D.ryuに統一
- Redbubble自動化は永久廃止（Cloudflare Turnstile）
- summary.pyがATTACK/VOLTをsummary.jsonに統合済み（2026-05-01）
