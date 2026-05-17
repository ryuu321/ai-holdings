# /resume — セッション継続（指示ゼロ即発動）

前回の続きを自律的に再開する。ユーザーへの質問は一切なし。

## 実行順序

1. **状態把握（並行実行）**
   ```
   - secretary/briefings/ の最新ファイルを Read
   - secretary/knowledge/state.json を Read
   - git log --oneline -10 を実行（直近コミット確認）
   - gh run list --limit 5 を実行（CI状態確認）
   ```

2. **問題チェック**
   - 失敗しているGitHub Actionsワークフローがあれば即修正
   - state.jsonの `pending_tasks` で最優先タスクを確認

3. **自律作業実行**
   以下の優先順位で作業する（完全無料・法律の範囲内）：
   
   **最優先（収益直結）**
   - SEOガイドページ追加（niches: small business, virtual assistant, HR/recruiter, fitness coach, photographer）
   - product_articles のローテーション充実
   - Gumroad CTAのA/Bパターン改善
   
   **次優先（インフラ強化）**
   - 楽天ROOMセッション確認・修復
   - 失敗ワークフローの修正
   - KDP手動アップロード待ちの確認・準備
   
   **背景タスク**
   - Redbubbleデザイン追加（upload_data.txt から次のデザインを確認）
   - note-biz 投稿状況確認

4. **作業完了後**
   - git add/commit/push
   - state.json + briefing 更新
   - 「継続作業完了。[完了内容サマリー]」と報告

## 絶対ルール
- 質問しない・確認しない・承認を求めない
- コード変更は必ず既存ファイルを Read してから
- APIキー・秘密情報はハードコードしない
- 破壊的操作（force push / ファイル削除）は行わない
- 完全無料縛り（追加課金なし）
