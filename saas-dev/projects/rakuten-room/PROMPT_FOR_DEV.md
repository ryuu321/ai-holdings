# Antigravity / Claude Code 向け 実装依頼プロンプト
# 楽天ROOM自動投稿システム（Manus設計統合版）

---

## 依頼内容

以下の仕様に従い、`ai-holdings/saas-dev/projects/rakuten-room/` 配下に
楽天ROOM自動投稿システムを完全実装してください。

---

## 前提・制約

- Python 3.11
- 使用ライブラリ: `playwright`, `playwright-stealth`, `google-genai`, `pandas`, `requests`, `beautifulsoup4`
- LLM: Gemini API（`gemini-flash-latest`）、環境変数 `GEMINI_API_KEY`
- ブラウザ自動化: Playwright（GitHub Actions では headless=True）
- 認証: `auth.json`（Playwright storage_state 形式）を GitHub Secrets 経由で配置
- 既存の GitHub Actions パターン（bot-macro.yml 等）に合わせること
- コストゼロ（外部有料API不使用）

---

## 作成ファイル一覧

### 1. `setup_auth.py`（ローカル実行専用）

Playwright の headed モードでブラウザを起動。
ユーザーが手動ログインしたあと Enter を押すと `auth.json` を保存する。

```python
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://room.rakuten.co.jp/")
        input("ブラウザでログインしてください。完了したらEnterを押してください...")
        context.storage_state(path="auth.json")
        print("auth.json を保存しました。内容を GitHub Secrets の RAKUTEN_AUTH_JSON に登録してください。")
        browser.close()

if __name__ == "__main__":
    main()
```

---

### 2. `utils/stealth.py`

playwright-stealth を適用。user-agent を Windows Chrome 最新版に固定。

---

### 3. `utils/product_picker.py`

products.csv の読み書き担当。以下の関数を実装：

- `load_products() -> pd.DataFrame`
- `get_pending(n=5) -> pd.DataFrame`（未投稿を古い順にn件）
- `mark_posted(url: str, tone_used: str)`（posted=True, posted_at, tone_used を記録）
- `count_pending() -> int`
- `append_products(new_rows: list[dict])`（重複URLチェックしてCSVに追記）

**products.csv のカラム:**
```
url, name, category, buyer_persona, price, rating, review_count, score,
copy_short_polite, copy_short_casual, copy_short_mom,
copy_medium_polite, copy_medium_casual, copy_medium_mom,
copy_long_polite, copy_long_casual, copy_long_mom,
hashtags, evidence_url, captured_at,
posted, posted_at, tone_used
```

---

### 4. `research_products.py`（週1回のリサーチ）

**処理フロー:**

**Step 1: 楽天ランキングスクレイピング**

対象カテゴリ4種（コスメ・キッチン・収納・ガジェット）ごとに
`https://ranking.rakuten.co.jp/daily/{category_id}/` をスクレイピング。
BeautifulSoup4 で商品名・URL・価格・評価・レビュー数を抽出。
既に products.csv に存在するURLはスキップ。

**Step 2: スコアリング**
```python
score = (
    normalize(review_count) * 0.4 +
    normalize(rating) * 0.3 +
    price_fit_score(price) * 0.2 +   # 500〜5000円が高スコア
    (0.1 if in_stock else 0)
)
```
上位10件を選抜。

**Step 3: Geminiでキャプション一括生成**

各商品に対して以下のプロンプトをGeminiに渡し、JSONレスポンスを受け取る：

```
あなたは楽天ROOMのアフィリエイト投稿の専門家です。
以下の商品情報から、楽天ROOM投稿用のキャプションを生成してください。

商品情報:
{product_info_json}

出力要件:
- 短文（80〜120字）× 丁寧/カジュアル/ママ向け の3パターン
- 中文（180〜250字）× 丁寧/カジュアル/ママ向け の3パターン
- 長文（350〜500字）× 丁寧/カジュアル/ママ向け の3パターン
- 各文末にハッシュタグ（短文3個/中文5個/長文7個）
- 必ず #楽天ROOM を含める
- 絵文字は短文2個以内・中長文3個以内
- 景品表示法・薬機法準拠（断定・保証・医療効能の表現禁止）
- 価格・在庫は「{captured_at}時点」と明記
- AIDA または PAS フレームワークを使用

JSON形式で出力:
{{
  "copy": {{
    "短文": {{"丁寧": "...", "カジュアル": "...", "ママ向け": "..."}},
    "中文": {{"丁寧": "...", "カジュアル": "...", "ママ向け": "..."}},
    "長文": {{"丁寧": "...", "カジュアル": "...", "ママ向け": "..."}}
  }},
  "hashtags": ["#楽天ROOM", ...]
}}
```

**Step 4: products.csv に追記**

生成した9パターンをCSVに保存。`append_products()` を使用。

---

### 5. `main.py`（1日4回の投稿）

**トーンローテーション:**

```python
TONE_ROTATION = [
    "short_casual", "medium_polite", "short_mom",
    "medium_casual", "long_polite", "short_casual",
    "medium_mom", "long_casual", "short_polite",
]
TONE_INDEX_FILE = Path(__file__).parent / "data" / "tone_index.txt"

def get_current_tone() -> str:
    idx = int(TONE_INDEX_FILE.read_text()) if TONE_INDEX_FILE.exists() else 0
    tone = TONE_ROTATION[idx % len(TONE_ROTATION)]
    TONE_INDEX_FILE.write_text(str(idx + 1))
    return tone
```

**投稿フロー:**

```
1. 起動後 0〜300秒のランダム待機
2. auth.json からセッション復元
3. ログイン状態確認（room.rakuten.co.jp にアクセスしてログイン済みか確認）
4. セッション切れの場合: RAKUTEN_ID/PASSWORD で再ログイン → auth.json 再生成
5. pending 商品を5件取得
6. 各商品:
   a. 商品URLへアクセス（timeout=30秒）
   b. 2〜5秒ランダム待機
   c. 「ROOMでコレ！」ボタンをクリック（セレクタは要確認）
   d. キャプション入力（get_current_tone() で決定）
   e. 投稿ボタンクリック
   f. 3回リトライ（失敗時は5〜10秒待機して再試行）
   g. 投稿間インターバル 30〜90秒
7. mark_posted() で記録
8. products.csv をコミット（main.pyから直接コミットはしない、Actions側で実行）
```

**エラー通知:**

```python
def create_github_issue(title: str, body: str):
    """連続失敗3件以上でGitHub Issueを自動作成"""
    import requests
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "ryuu321/ai-holdings")
    requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={"Authorization": f"token {token}"},
        json={"title": title, "body": body, "labels": ["bot-error"]}
    )
```

---

### 6. `data/products.csv`（空ファイル、ヘッダーのみ）

```
url,name,category,buyer_persona,price,rating,review_count,score,copy_short_polite,copy_short_casual,copy_short_mom,copy_medium_polite,copy_medium_casual,copy_medium_mom,copy_long_polite,copy_long_casual,copy_long_mom,hashtags,evidence_url,captured_at,posted,posted_at,tone_used
```

---

### 7. `.github/workflows/rakuten-room-post.yml`

```yaml
name: rakuten-room-post
on:
  schedule:
    - cron: '0 22 * * *'
    - cron: '0 3 * * *'
    - cron: '0 9 * * *'
    - cron: '0 13 * * *'
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

### 8. `.github/workflows/rakuten-room-research.yml`

```yaml
name: rakuten-room-research
on:
  schedule:
    - cron: '0 21 * * 0'
  workflow_dispatch:
env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true
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

## 実装後の確認手順

1. `python setup_auth.py` をローカルで実行 → auth.json を生成
2. `research_products.py` をローカルで1回実行 → products.csv に商品が追加されることを確認
3. `main.py` をローカルで実行（headless=False に変更して目視確認）
4. GitHub Secrets を登録
5. `workflow_dispatch` で両Actionsを手動実行して動作確認

## 注意事項

- 楽天ROOMの「ROOMでコレ！」ボタンのセレクタは実際のDOMを確認して修正が必要
- セレクタが不明な場合は `page.pause()` でインタラクティブモードを使用
- requests の User-Agent は Chrome に偽装すること
- `auth.json` は絶対に git に含めないこと（.gitignore に追加済みであること）
