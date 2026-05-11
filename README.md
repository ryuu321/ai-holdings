# AI Holdings — Claude Code マルチエージェント企業グループ

## 概要
Claude Codeを使って、5つの事業会社を持つAIエージェント企業グループを動かすシステムです。

## 会社構成
```
ai-holdings/
├── CLAUDE.md              # ホールディングスCEO
├── run.py                 # CEOオーケストレーター（エントリーポイント）
├── shared/
│   ├── memory/
│   │   └── context.json   # 全社共通コンテキスト
│   └── logs/              # 実行ログ
│
├── saas-dev/              # SaaS開発社
│   ├── CLAUDE.md          # 社長（PM）
│   ├── backend/CLAUDE.md  # バックエンドエンジニア
│   ├── frontend/CLAUDE.md # フロントエンドエンジニア
│   └── qa/CLAUDE.md       # QA
│
├── note-biz/              # note副業社
│   ├── CLAUDE.md          # 社長（編集長）
│   ├── researcher/CLAUDE.md
│   ├── writer/CLAUDE.md
│   └── seo/CLAUDE.md
│
├── sns-ops/               # SNS運用社
│   ├── CLAUDE.md          # 社長（ブランドマネージャー）
│   ├── post-gen/CLAUDE.md # 投稿生成
│   ├── trend/CLAUDE.md    # トレンド分析
│   └── reply/CLAUDE.md    # 返信対応
│
├── consulting/            # コンサル社
│   ├── CLAUDE.md          # 社長
│   ├── analyst/CLAUDE.md  # アナリスト
│   └── marketer/CLAUDE.md # マーケター
│
└── macro-biz/             # マクロBiz社
    ├── CLAUDE.md          # 社長（チーフストラテジスト）
    ├── market-research/CLAUDE.md
    └── bizmodel/CLAUDE.md
```

## クイックスタート

### 必要なもの
- Claude Code（`claude` コマンドが使える状態）
- Python 3.10以上

### 基本的な使い方

```bash
# このディレクトリに移動
cd ai-holdings

# CEOにタスクを投げる（自動で担当会社に振り分け）
python run.py "AIエージェントを使った業務効率化サービスのアイデアを出して"

# 特定の会社の社長に直接指示する場合
claude --print -p "$(cat saas-dev/CLAUDE.md)" "ToDoアプリのAPI設計をして"
claude --print -p "$(cat note-biz/CLAUDE.md)" "AIエージェント入門記事を企画して"
```

### Claude Code の会社ディレクトリで起動する場合

```bash
# 各社のディレクトリで起動すると、CLAUDE.mdが自動で読まれる
cd ai-holdings/saas-dev
claude  # → SaaS開発社の社長として動作
```

## シナジーの活用例

### 例1: 新プロダクトリリース
```bash
python run.py "タスク管理SaaSをリリースしたい。開発・告知・記事・マーケ全部やって"
# → CEO がSaaS開発社・SNS運用社・note副業社に並列委任
```

### 例2: コンテンツマーケティング
```bash
python run.py "AIコンサルの見込み客を増やしたい"
# → CEO がコンサル社・note副業社・SNS運用社に連携指示
```

## カスタマイズ
各 `CLAUDE.md` を編集して、エージェントの性格・得意領域・出力形式を調整できます。
