# /end — セッション終了処理

今日の会話を記録して次のセッションに引き継ぐ。

## 実行順序

1. **決定事項チェック（頭の中で確認）**
   - 今日「〇〇する」と決まったことは何か
   - 今日「〇〇はやらない」と決まったことは何か
   - 優先順位が変わったことはあるか
   - 完了したタスクは何か / 新たに発生したタスクは何か

2. **daily-log を保存**
   - ファイル: `secretary/daily-logs/YYYY-MM-DD.md`
   - 形式: 今日やったこと / 決定事項 / やらないと決めたこと / 明日やること（優先順位）

3. **context ファイルを更新（変化のあった会社のみ）**
   - `secretary/context/{会社名}.md` を更新

4. **state.json を更新**
   - `last_updated`, `session_count` +1
   - 変化のあった会社の wins / issues / status
   - `group_strategy.key_decisions`: 今日の決定事項を追加
   - `pending_tasks`: 完了分削除・新規分追加
   - `next_session_agenda`: 明日の最優先3件

5. **翌朝のブリーフィングを作成**
   - ファイル: `secretary/briefings/YYYY-MM-DD-morning.md`
   - 形式: 昨日の主な成果 / 今日のアジェンダ / 気になる数字 / 一言

6. **報告**
   「記録しました。また明日！」で締める。
