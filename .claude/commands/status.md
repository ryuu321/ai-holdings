# /status — グループ全体の現状確認

`secretary/knowledge/state.json` と `secretary/briefings/` の最新ファイルを読んで、グループ全体の状況を報告する。

## 手順

1. `secretary/knowledge/state.json` を読む
2. `secretary/briefings/` の最新ファイルを読む（あれば「前回の成果」に使う）
3. 以下の形式で出力する

## 出力フォーマット

```
AI Holdings ステータス — {last_updated}

[グループ戦略]
  フォーカス: {current_focus}
  四半期目標: {quarter_goal}

[各社状況]
  saas-dev  ({status}): {最新wins1行} / 課題: {issues}
  note-biz  ({status}): {最新wins1行} / 課題: {issues}
  sns-ops   ({status}): {active_projects} / 課題: {issues}
  consulting({status}): {active_projects}
  macro-biz ({status}): {active_projects}

[積み残しタスク]
  {pending_tasksを番号付きで全件}

[やらないと決めたこと]
  {key_decisionsの中の「〜しない」系を抜粋}

[今日のアクション]
  1. {最優先・5分でできること} ← 最も止まっているもの
  2. {次に重要なこと}
  3. {余裕があれば}

何から始めますか？
```

## 注意
- state.json にないことは推測しない
- 「やらないと決めたこと」セクションは必ず含める
- 各社の status が「初期」「準備中」のまま長期間の場合は注記する
- アジェンダは3件まで。多くしない。
