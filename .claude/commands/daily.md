# /daily — 日課を実行する

`shared/tools/daily-routine.md` の手順に従って日課を実行する。

## 実行手順

1. `shared/tools/daily-routine.md` を読んで手順を確認する
2. 投資ボットレポートを表示する
   ```bash
   cd saas-dev/projects/auto-invest && python shared/tools/daily_report.py 2>/dev/null || echo "データなし"
   ```
3. `shared/knowledge/` から今日の記事ネタを1つ選んで `note-biz/output/YYYY-MM-DD_article.md` に生成する
4. X投稿文3本を `sns-ops/output/YYYY-MM-DD_tweets.md` に生成する
5. 今日のサマリーを表示する（あなたがやること5分を提示）

## 記事生成のルール
- `note-biz/skills/article-generator.md` のフォーマットに従う
- テーマは `shared/knowledge/love/` のナレッジから引く
- 3,000字以上・有料部分の引きを必ず入れる

## X投稿文のルール
- チビの哲学ブランドの語り口（〜んですよね調）
- 1本目: 恋愛の本質系（インプレッション狙い）
- 2本目: note誘導（「詳しくはnoteに書いた」）
- 3本目: 日常観察系（親近感）
