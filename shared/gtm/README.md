# GTM Framework — 収益化マニュアル

saas-build（開発 Phase 0-11）の続き。製品を作った後に「誰に・どう届けるか」を再現可能にする。

## 使い方

1. `config/{project_name}.json` にICP・製品情報を書く
2. `python leads/fetch_leads.py --project {name}` でリード収集
3. `python leads/qualify_leads.py --project {name}` で品質フィルタリング
4. `leads_review.csv` を人間が目視確認 → `leads_approved.csv` に移動
5. `python outreach/generate_emails.py --project {name}` でメール生成
6. `python outreach/send_emails.py --project {name} --dry-run` でプレビュー確認
7. OK なら `--dry-run` を外して本番送信（最大30件/日）
8. `python analytics/metrics.py --project {name}` でKPI確認

## フェーズ対応表

| saas-build Phase | GTM Phase | 内容 |
|-----------------|-----------|------|
| Phase 12 | GTM戦略設計 | ICP・チャネル・メッセージ定義 |
| Phase 13 | リード収集 | fetch_leads → qualify_leads |
| Phase 14 | メッセージング | generate_emails → dry-run確認 |
| Phase 15 | 送信・追跡 | send_emails → funnel管理 |
| Phase 16 | PDCAループ | metrics → analyze → テンプレート改善 |

## ディレクトリ構成

```
shared/gtm/
├── config/{project}.json    ← ICP・製品情報・スコアリングルール
├── leads/
│   ├── fetch_leads.py       ← Brave Search APIでリード収集
│   └── qualify_leads.py     ← ICPスコアリング (0-100点)
├── outreach/
│   ├── generate_emails.py   ← Geminiでパーソナライズ生成
│   ├── send_emails.py       ← Gmail SMTP送信（--dry-run必須）
│   └── templates/           ← メールテンプレート群
├── analytics/
│   └── metrics.py           ← KPI出力
└── data/{project}/
    ├── leads_approved.csv   ← 送信可（80点以上）
    ├── leads_review.csv     ← 要人間確認（60-79点）
    ├── leads_rejected.csv   ← 自動却下（60点未満）
    ├── emails_draft.csv     ← 生成済み未送信
    ├── sent_log.csv         ← 送信履歴
    └── funnel.csv           ← ファネルステージ管理
```

## 倫理・法令チェックリスト（送信前に必須）

### 時間帯・頻度
- [ ] **JST 9:00〜18:00 以外は送らない** — send_emails.py に時間帯チェック実装済み（`--force-send` で回避可能だが非推奨）
- [ ] **1日上限30件** — Gmail 信頼スコア保護と受信者への配慮
- [ ] **同一会社への重複送信なし** — sent_log.csv と emails_draft.csv の両方でチェック

### データ品質（送って恥ずかしくないか）
- [ ] **会社名の確認** — scraped page title がそのまま入っていないか（`--dry-run` で目視確認）
- [ ] **fake email の除外** — `@mail.jp`, `@sample.co.jp`, `@sample.jp`, `@example.com` 等は送らない
- [ ] **無関係業種の除外** — 求人・協会・工務店・ビル管理への誤送信は信頼を損なう
- [ ] **1社1アドレス** — 同じ会社の複数アドレスは同日に送らない

### 特定電子メール法準拠
- [ ] オプトアウト文言（「ご不要の場合はご返信を」）が含まれているか
- [ ] 送信者の本名が本文に含まれているか
- [ ] 返信があった場合に sent_log を `replied` に更新して再送しない仕組みがあるか

### コンテンツ
- [ ] `--dry-run` で全送信予定メールをプレビュー
- [ ] personalized=False の件が20%超えていないか（Gemini 429対策）
- [ ] `--limit` が30以下か

---

## 実戦知見ライブラリ（踏んだ地雷集）

### リード収集

**① スクレイピングした「会社名」はページタイトル**
- Brave 検索結果の `title` はページタイトル。「名古屋市でおすすめの不動産会社ランキング23選」が company_name になる
- そのまま送ると「名古屋市でおすすめの不動産会社ランキング23選2025 ご担当者様」という宛名になる
- **解決策**: `--dry-run` で1件ずつ目視確認。長すぎる/不自然な会社名は手動で修正してから送信

**② qualify_leads.py のスコアはページタイトルを入力とする問題**
- 除外キーワード「ランキング」「一覧」が会社名ではなくページタイトルに入っているため誤却下が発生する
- 本来は優良リードなのにスコア 0 点で弾かれる（例: azway.co.jp が「ランキング23選」ページ経由で拒否）
- **解決策**: `leads_review.csv` を必ず人間が確認。`leads_rejected.csv` も一度目を通す

**③ placeholder email が approved に混入する**
- `info@sample.co.jp`, `info@mail.jp`, `mail@sample.jp` → ICPスコア的には通過する
- **解決策**: qualify_leads.py の除外チェックに placeholder ドメインリストを追加する
```python
PLACEHOLDER_DOMAINS = {"sample.co.jp", "sample.jp", "mail.jp", "example.com", "example.co.jp"}
if domain in PLACEHOLDER_DOMAINS:
    score += scoring["exclude_keyword_penalty"]  # -50点
```

### メール送信

**④ 深夜送信は印象が致命的**
- 自律エージェントで「今すぐやっておいて」と指示された場合でも、外部送信は営業時間内に限る
- JST 3時台に送ったメールは受信者が翌朝開封。「深夜に自動送信してくる業者」という印象になる
- **解決策**: send_emails.py の冒頭で時間帯チェック（実装済み）。エージェントへの指示時も時間を確認

**⑤ 同一会社への重複接触**
- taft@taft.co.jp（送信済み）と kanri@taft.co.jp（別部署）を同日に送るのは過剰
- **解決策**: qualify 後に同一ドメインの複数アドレスが approved に入っていないか確認する

### Brave Search API

**⑥ 同じクエリは同じ結果を返す**
- 2回目以降は新しいリードが取れない。クエリのバリエーションが重要
- **解決策**: QUERIES リストに都市・業態・キーワードの組み合わせを30件以上用意する
- クエリの多様性 = リードの多様性。「不動産仲介 東京 メール」を10回叩いても同じURL

**⑦ サイトフェッチは robots.txt を考慮していない**
- fetch_mlit_leads.py は直接 HTML を取得する。過度なフェッチは相手サーバに負荷をかける
- **現状**: sleep(1.0)/サイト でアクセス制限あり。これ以上高速化しない
