# 仕様書：楽天ROOM自動投稿システム v3.0
# AI Holdings / saas-dev / rakuten-room
# Manus プロンプト設計を統合した完全自動化版

---

## 1. プロジェクト概要

GitHub Actions で完全自動化する楽天ROOM投稿システム。
**週1回のリサーチパイプライン**が商品を自動発掘・キャプション生成し、
**1日4回の投稿パイプライン**が自動投稿する。人力ゼロ。

---

## 2. パイプライン全体像

```
【週1回 月曜 JST 6:00】
research_products.py
  1. Gemini に Manus スタイルのリサーチプロンプトを渡す
  2. 楽天ランキングをスクレイピング（requestsで十分、Playwright不要）
  3. 上位商品のレビューを解析 → 仕様をベネフィットに翻訳
  4. 短/中/長 × 丁寧/カジュアル/ママ向け = 9パターンのキャプション生成
  5. products.csv に追記（重複チェックあり）

【1日4回 JST 7:00 / 12:00 / 18:00 / 22:00】
main.py
  1. auth.json でセッション復元
  2. products.csv から未投稿5件取得
  3. Playwright で楽天ROOMに投稿
  4. トーンをローテーション（丁寧→カジュアル→ママ向け→...）
  5. 投稿済みフラグ更新・CSV コミット
```

---

## 3. ディレクトリ構成

```
ai-holdings/
  saas-dev/projects/rakuten-room/
    main.py                  # 投稿メインロジック（Playwright）
    research_products.py     # 商品リサーチ＋キャプション生成（Gemini）
    setup_auth.py            # 初回のみ: auth.json 生成（ローカル実行）
    utils/
      stealth.py             # Playwright stealth設定
      product_picker.py      # products.csv の読み書き
    data/
      products.csv           # 商品マスタ（全キャプション含む）
    auth.json                # gitignore済み
  .github/workflows/
    rakuten-room-post.yml    # 投稿（1日4回）
    rakuten-room-research.yml # リサーチ（週1回）
```

---

## 4. products.csv スキーマ

```
url            : 楽天商品ページURL
name           : 商品名
category       : カテゴリ（収納/キッチン/コスメ等）
buyer_persona  : ターゲット（一人暮らし/子育て世帯/在宅ワーカー等）
price          : 価格（税込、取得時点）
rating         : 平均評価
review_count   : レビュー数
score          : リサーチスコア（0.0〜1.0）
copy_short_polite   : 短文・丁寧（80〜120字＋ハッシュタグ3個）
copy_short_casual   : 短文・カジュアル
copy_short_mom      : 短文・ママ向け
copy_medium_polite  : 中文・丁寧（180〜250字＋ハッシュタグ5個）
copy_medium_casual  : 中文・カジュアル
copy_medium_mom     : 中文・ママ向け
copy_long_polite    : 長文・丁寧（350〜500字＋ハッシュタグ7個）
copy_long_casual    : 長文・カジュアル
copy_long_mom       : 長文・ママ向け
hashtags       : 推奨ハッシュタグ（カンマ区切り）
evidence_url   : 根拠URL（ランキングページ等）
captured_at    : 商品情報取得日時（YYYY-MM-DD HH:MM）
posted         : 投稿済みフラグ（False/True）
posted_at      : 投稿日時
tone_used      : 使用したトーン（short_polite等）
```

---

## 5. research_products.py 仕様

### 5.1 商品リサーチ（Manusワークフロー準拠）

```python
# 対象カテゴリ（設定で変更可能）
CATEGORIES = [
    {"id": "cosme", "name": "コスメ・美容", "persona": "20〜30代女性"},
    {"id": "kitchen", "name": "キッチン用品", "persona": "子育て世帯"},
    {"id": "storage", "name": "収納・インテリア", "persona": "一人暮らし/在宅ワーカー"},
    {"id": "gadget", "name": "ガジェット・家電", "persona": "在宅ワーカー"},
]

# リサーチ対象URL（週替わりで収集）
RAKUTEN_RANKING_URLS = [
    "https://ranking.rakuten.co.jp/daily/{category}/",
    "https://ranking.rakuten.co.jp/weekly/{category}/",
]
```

### 5.2 スコアリング

```
score = (
    normalize(review_count) * 0.4 +
    normalize(rating) * 0.3 +
    price_fit_score * 0.2 +       # 500〜5000円が高スコア
    in_stock_bonus * 0.1           # 在庫ありは+0.1
)
```

### 5.3 Geminiへのリサーチプロンプト設計

`[MANUS_PROMPT]` をベースに、以下のJSONを渡してキャプションを一括生成：

```json
{
  "category": "{category}",
  "buyer_persona": "{persona}",
  "price_range_jpy": {"min": 500, "max": 8000},
  "min_review_count": 50,
  "min_rating": 4.0,
  "copy_tones": ["丁寧", "カジュアル", "ママ向け"],
  "hashtags_core": ["#楽天ROOM", "#楽天市場"],
  "event_tags": ["#楽天スーパーSALE", "#お買い物マラソン", "#5と0のつく日"],
  "product_data": { ...スクレイピングした商品情報... }
}
```

出力形式（Geminiからのレスポンス）:
```json
{
  "copy": {
    "短文": {"丁寧": "...", "カジュアル": "...", "ママ向け": "..."},
    "中文": {"丁寧": "...", "カジュアル": "...", "ママ向け": "..."},
    "長文": {"丁寧": "...", "カジュアル": "...", "ママ向け": "..."}
  },
  "hashtags": ["#楽天ROOM", ...],
  "score": 0.82
}
```

---

## 6. main.py 仕様（投稿ロジック）

### 6.1 トーンローテーション

投稿のたびに以下の順でトーンを切り替える（単調にならないように）:

```python
TONE_ROTATION = [
    "short_casual",
    "medium_polite",
    "short_mom",
    "medium_casual",
    "long_polite",
    "short_casual",
    "medium_mom",
    "long_casual",
    "short_polite",
]
# 現在インデックスをtone_rotation_index.txtに保存して次回継続
```

### 6.2 投稿フロー（Playwright）

```
1. auth.json からセッション復元
2. セッション確認（ログイン状態チェック）
3. 商品URLへアクセス
4. 「ROOMでコレ！」ボタンをクリック
5. キャプション入力（tone_rotationで決定したもの）
6. 投稿ボタンをクリック
7. 成功確認（遷移先URLまたは完了メッセージで判定）
8. posted=True, tone_used を記録
```

### 6.3 エラーハンドリング

| エラー | 対処 |
|--------|------|
| 要素タイムアウト | 3回リトライ後スキップ |
| セッション切れ | RAKUTEN_ID/PASSで再ログイン → auth.json更新 |
| 投稿上限検知 | 即日停止 → 翌日再開 |
| Gemini APIエラー | プリセット5種からランダム選択 |
| 全件失敗3日連続 | GitHub Issues に自動起票 |

---

## 7. GitHub Actions 設定

### rakuten-room-post.yml（1日4回）

```yaml
name: rakuten-room-post
on:
  schedule:
    - cron: '0 22 * * *'   # JST 07:00
    - cron: '0 3 * * *'    # JST 12:00
    - cron: '0 9 * * *'    # JST 18:00
    - cron: '0 13 * * *'   # JST 22:00
  workflow_dispatch:

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

jobs:
  post:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      issues: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install playwright playwright-stealth pandas requests
      - run: playwright install chromium
      - run: echo '${{ secrets.RAKUTEN_AUTH_JSON }}' > saas-dev/projects/rakuten-room/auth.json
      - name: 投稿実行
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          RAKUTEN_ID: ${{ secrets.RAKUTEN_ID }}
          RAKUTEN_PASSWORD: ${{ secrets.RAKUTEN_PASSWORD }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
        run: cd saas-dev/projects/rakuten-room && python -u main.py
      - name: CSVをコミット
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add saas-dev/projects/rakuten-room/data/
          git diff --cached --quiet || git commit -m "chore: rakuten-room post $(date -u '+%Y-%m-%dT%H:%M')"
          git pull --rebase && git push
```

### rakuten-room-research.yml（週1回）

```yaml
name: rakuten-room-research
on:
  schedule:
    - cron: '0 21 * * 0'   # JST 月曜 06:00
  workflow_dispatch:

jobs:
  research:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install google-genai pandas requests beautifulsoup4
      - name: リサーチ実行
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
        run: cd saas-dev/projects/rakuten-room && python -u research_products.py
      - name: CSVをコミット
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add saas-dev/projects/rakuten-room/data/products.csv
          git diff --cached --quiet || git commit -m "chore: rakuten-room research $(date -u '+%Y-%m-%dT%H:%M')"
          git pull --rebase && git push
```

---

## 8. セキュリティ・規約

- auth.json は gitignore 済み（GitHub Secrets経由のみ）
- 価格・在庫はすべて「取得日時点」を明記
- 景品表示法・薬機法準拠（断定・保証・医療効能の表現禁止）
- playwright-stealth でBOT検知回避
- リクエスト間に 30〜90秒のランダム待機

---

## 9. 初期セットアップ手順（開発後）

1. `python setup_auth.py` をローカル実行 → auth.json 生成
2. GitHub Secrets に登録：
   - `RAKUTEN_AUTH_JSON`（auth.jsonの全文）
   - `RAKUTEN_ID`
   - `RAKUTEN_PASSWORD`
   - `GEMINI_API_KEY`（既存キー）
3. `workflow_dispatch` で research を手動実行 → products.csv に商品追加
4. `workflow_dispatch` で post を1回手動実行 → 動作確認
5. 自動スケジュール開始
