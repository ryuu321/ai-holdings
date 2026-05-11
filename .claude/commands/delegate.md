# /delegate [会社名] [タスク内容] — サブエージェントに委任

メインコンテキストを汚染せず、独立したサブエージェントに委任する。

## 実行手順

1. 引数から `[会社名]` と `[タスク]` を取得
2. 以下を**並列で**読む:
   - `{会社名}/CLAUDE.md`
   - `secretary/context/{会社名}.md`
3. **Agentツールでサブエージェントを起動**
4. 結果を受け取りユーザーに報告（5行以内）
5. `secretary/context/{会社名}.md` を更新

## Agentへ渡すプロンプト

```
あなたは {会社名} のエージェントです。

## あなたのCLAUDE.md
{会社CLAUDE.mdの内容}

## 現在の状況
{secretary/context/{会社名}.md の内容}

## 依頼タスク
{タスク内容}

## ルール
- 判断に迷ったら合理的に進める
- 変更したファイルのパスを列挙して返す
- 結果サマリーは5行以内
- 完了後に secretary/context/{会社名}.md を最新状態に更新する
```

## 対応会社

| 会社名 | CLAUDE.md | context |
|--------|-----------|---------|
| saas-dev | saas-dev/CLAUDE.md | secretary/context/saas-dev.md |
| note-biz | note-biz/CLAUDE.md | secretary/context/note-biz.md |
| sns-ops | sns-ops/CLAUDE.md | secretary/context/sns-ops.md |
| research | research/CLAUDE.md | secretary/context/research.md |
| consulting | consulting/CLAUDE.md | secretary/context/consulting.md |
