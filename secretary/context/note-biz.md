---
company: note-biz
updated: 2026-05-01
---

## 稼働中プロジェクト
- 全自動3アカウント 毎日JST10時投稿（GitHub Actions）
- KDP × note CTAシナジー（関連Kindle本を有料部分末尾に自動挿入）

## アカウント
| ID | アカウント名 | ジャンル | セッションSecret | 有効期限 |
|----|------------|---------|----------------|---------|
| 1 | takumi_ai_f | AI副業・ChatGPT活用 | NOTE_SESSION_1 | 2026-07-25 |
| 2 | yuuki_nisa | 節約・投資入門 | NOTE_SESSION_2 | 2026-07-25 |
| 3 | ken_nenshu_up | 転職・キャリア | NOTE_SESSION_3 | 2026-07-25 |

## 重要パス
- 投稿スクリプト: `saas-dev/projects/note-auto/`
- 状態ファイル: `saas-dev/projects/note-auto/state_{1,2,3}.json`
- ワークフロー: `.github/workflows/` の note-auto 系

## note.com APIメモ
- 下書き: POST /api/v1/text_notes
- 公開: PUT /api/v1/text_notes/{id}（status=published）
- 有料422時は無料フォールバック済み

## 現在の課題
- 有料記事: 口座登録済み・有料公開ワークフローが実際に動作しているか未確認
- Gemini 503エラー: 4回リトライ（60/120/180/240s）で基本回避

## Geminiモデル
- 使用可能: gemini-flash-latest のみ

## 廃止
- チビの哲学（恋愛哲学ブランド）: 2026-05-01廃業決定
