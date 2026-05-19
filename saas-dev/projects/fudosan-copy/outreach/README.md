# FudoText アウトリーチ自動化

1日100件の不動産会社へのコールドメール自動送信パイプライン。

## フロー

```
fetch_mlit_leads.py  →  urls.txt
collect_leads.py     →  leads.csv       (メアドスクレイピング)
generate_emails.py   →  emails_draft.csv (Geminiでパーソナライズ)
send_emails.py       →  sent_log.csv    (Gmail SMTP送信)
```

## セットアップ（初回のみ）

### 1. Gmailアプリパスワード取得
1. Google アカウント → セキュリティ → 2段階認証 ON
2. アプリパスワード → 「メール」→ 16文字のパスワードを控える

### 2. 環境変数設定（PowerShell）
```powershell
$env:GMAIL_ADDRESS = "ryuumg03@gmail.com"
$env:GMAIL_APP_PASSWORD = "xxxx xxxx xxxx xxxx"
$env:GEMINI_API_KEY = "your-key"
```

## 毎日の実行手順

```powershell
cd saas-dev/projects/fudosan-copy/outreach

# Step 1: URLリスト収集（初回 or 週1）
python fetch_mlit_leads.py

# Step 2: メアドスクレイピング
python collect_leads.py

# Step 3: メール文生成（Geminiでパーソナライズ）
python generate_emails.py

# Step 4: 送信（100件/日）
python send_emails.py
```

## ファイル説明

| ファイル | 内容 |
|---------|------|
| `urls.txt` | 収集した不動産会社URL一覧 |
| `leads.csv` | 会社名・メアド・URL |
| `emails_draft.csv` | 生成済みメール（draft/sent） |
| `sent_log.csv` | 送信履歴（重複防止） |

## メール構成

- 件名: 【無料】物件説明文をAIで30秒に短縮するツールを作りました
- 冒頭: 会社ごとにGeminiがパーソナライズ（1〜2文）
- 本文: FudoText の価値提案 + 無料トライアルCTA
- 末尾: オプトアウト案内（特定電子メール法対応）
