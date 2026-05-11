# 日課ルーティン — CEOエージェント手順書

ユーザーが「今日の日課実行して」と言ったら、以下を順番に実行する。

---

## Step 1: 投資ボットレポート

```bash
cd shared/tools && python daily_report.py
```

結果をユーザーに表示する。

---

## Step 2: ナレッジベースから記事生成

`shared/knowledge/love/` のファイルを読み込み、
まだ記事化されていないエピソード・哲学を1つ選んで
`note-biz/skills/article-generator.md` のテンプレートに従って記事を生成する。

生成した記事は以下に保存：
`note-biz/output/YYYY-MM-DD_article.md`

---

## Step 3: X投稿文を3本生成

Step 2で生成した記事と`shared/knowledge/love/`の内容を元に3本生成する。

ルール：
- 1本目: 恋愛Tips（ナレッジから独立したネタ・100字以内）
- 2本目: 自己肯定感・自信系Tips（100字以内）
- 3本目: Step 2の記事と連動したnote誘導（100字以内 + 「#チビの哲学」）

文体ルール：
- 断言調で短く（「〜です」「〜する」）
- 説教くさくしない
- 読んだ人が「わかる」と思う一言を必ず入れる

生成した投稿文は以下に保存：
`sns-ops/output/YYYY-MM-DD_tweets.md`

---

## Step 4: 今日のサマリーを表示

```
【今日の日課完了】
✔ 投資ボット: [状況]
✔ note記事: [タイトル] → note-biz/output/に保存済み
✔ X投稿文: 3本 → sns-ops/output/に保存済み

あなたがやること（5分）:
1. note-biz/output/の記事をnoteにコピペして公開
2. sns-ops/output/のツイートをXに投稿
```
