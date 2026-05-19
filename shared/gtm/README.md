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

## 誤送信防止チェックリスト

送信前に必ず確認:
- [ ] `--dry-run` で全送信予定メールをプレビュー
- [ ] 会社名が正しく抽出されているか（ページタイトルがそのまま入っていないか）
- [ ] personalized=False の件が20%超えていないか（Gemini 429対策）
- [ ] 特定電子メール法文言（オプトアウト案内・送信者本名）が含まれているか
- [ ] --limit が30以下か
