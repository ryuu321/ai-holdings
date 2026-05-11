# /kindle — Kindle KDP 管理

`saas-dev/projects/kindle-kdp/data/books.json` を読んで、出版状況を確認・管理する。

## 手順

1. `saas-dev/projects/kindle-kdp/data/books.json` を読む
2. 引数に応じて処理を分岐する

### 引数なし（デフォルト）
現在の出版状況を一覧表示する。

### `done [番号]`
指定した本を「published」に更新する。
- books.json の該当エントリの `status` を `"published"` に変更
- `kdp_url` に「手動アップロード済み」と記録
- 変更を保存する

### `generate`
次のEPUBを今すぐ生成する。
- GitHub Actions の `kindle-kdp-weekly.yml` を手動トリガー
- `gh workflow run kindle-kdp-weekly.yml --ref master` を実行

## 出力フォーマット（引数なし）

```
📚 Kindle KDP 状況 — 累計{N}冊生成

[アップロード待ち]
  #{番号} {タイトル}（{カテゴリ}）
      EPUB: output/{フォルダ名}/
      生成日: {generated_at}
  ※ アップロード済みなら `/kindle done {番号}` で記録

[出版済み]
  #{番号} {タイトル} ✓

[次回生成予定]
  毎週日曜 JST 07:00 自動実行
  今すぐ生成: `/kindle generate`

[KDP手順リマインド]
  1. output/{フォルダ}/ からEPUBとcover.jpgをダウンロード
  2. kdp.amazon.co.jp → 新しいタイトルを追加
  3. 価格: ¥980（70%ロイヤリティ → 約¥686/冊）
  4. 税務: W-8BEN Article 12, 0%設定済み確認
```

## 注意
- status が `epub_ready` = アップロード待ち
- status が `published` = KDPアップロード済み
- books.json を直接編集して保存すること（git commitは不要）
