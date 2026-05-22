---
company: saas-dev
updated: 2026-05-22
---

## 稼働中プロジェクト
- 投資ボット6本: SHORT/MEDIUM/LONG/MACRO/ATTACK/VOLT（GitHub Actions 4時間ごと/毎日/毎週）
- 楽天ROOM自動投稿: 1日4回（07/12/18/22時JST）・**現在セッション切れ中**・要ローカルauth更新
- Kindle KDP: EPUB自動生成（日曜・水曜 JST7時）累計6冊・手動アップロード待ち
- Redbubble: MidnightTorii 手動アップロード（next_index=4、残16件）
- ダッシュボード: docs/index.html（毎日JST7時自動生成）+ Flask app

## SaaS プロダクト（3本稼働中）

### FudoText（不動産仲介向け）
- LP: `docs/fudotext.html`（GitHub Pages公開済み）
- コールドメール: 8社送信済み（2026-05-19）・返信待ち
- Supabase: trials/codes/history テーブル稼働中
- Stripe: payment link 作成済み（setup_stripe.py で自動作成）
- PDCA: Google Forms CSV → Gemini 分析（週次・GitHub Actions）

### SharoText（社労士向け）
- アプリ: Streamlit Cloud 稼働中
- Supabase: trials/codes/history/feedback テーブル稼働中
- in-app フィードバック: 👍/👎 → `sharotext_feedback` テーブル
- Stripe: payment link 作成済み（スタンダード ¥8,980 / プロ ¥19,800）
- GitHub Actions: check-replies / follow-up / feedback-pdca 稼働中
- コールドメール: 送信中（sent_log Gist管理）

### KenText（建設・工務店向け）
- アプリ: Streamlit Cloud 稼働中
- Supabase: trials/codes/history/feedback テーブル稼働中
- in-app フィードバック: 👍/👎 → `kensetsu_feedback` テーブル
- Stripe: payment link 作成済み（スタンダード ¥8,980 / プロ ¥19,800）
- GitHub Actions: check-replies / follow-up / feedback-pdca 稼働中

## 新事業セットアップ（/saas-build スキル）
- `/saas-build {project}` → 名前 + 1往復 + コピペ2回 = 新事業完成
- `setup_stripe.py --project {name}` で自動完了するもの:
  - Stripe 決済リンク作成
  - sent_log Gist 作成
  - GitHub Secrets (`{PROJECT}_SENT_LOG_GIST_ID`) 登録
  - clipboard.txt: SQL + Streamlit Secrets の2点セット出力
- 手動作業は2ステップのみ: Supabase SQL実行 + Streamlit Cloud デプロイ

## Gumroad（ventures-auto 傘下）
- **9商品公開済み** / 売上 $0 / 全商品アフィリエイト25%設定済み

## 重要パス
- FudoText: `saas-dev/projects/fudosan-copy/`
- SharoText: `fudotext/saas-dev/projects/sharotext/`
- KenText: `fudotext/saas-dev/projects/kensetsu/`
- 新事業セットアップ: `shared/gtm/scripts/setup_stripe.py`
- GTM設定: `shared/gtm/config/{project}.json`
- GitHub Actions: `.github/workflows/{project}-*.yml`

## 現在の課題
- FudoText: 8社からの返信待ち（2026-05-19送信・3日経過）
- 楽天ROOM: セッション切れ（ローカルで `.\update_auth.ps1` 必須）
- KDP: 6冊のEPUBが未アップロード
- Gumroad売上 $0

## 直近の決定
- Stripe 復活: sk_live_ キーで payment link 作成成功（2026-05-22）
- in-app フィードバック標準化: Google Forms 不要・Supabase 直接保存（2026-05-22）
- /saas-build スキル全自動化: Gist + GitHub Secrets まで自動（2026-05-22）
- icp.document_types をconfig標準フィールドに追加（2026-05-22）
