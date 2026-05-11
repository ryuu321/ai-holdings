# Lessons Learned — 変わらない技術的事実

参照のみ。次セッションで自動読み込み不要（必要時のみ参照）。

- このGemini APIキーで使えるモデルは `gemini-flash-latest` のみ
- note.com公開API: `PUT /api/v1/text_notes/{id}`（status=published）
- Gemini 503は4回リトライ（60/120/180/240s）で基本回避可能
- GitHub Actionsはプライベートリポ2000分/月
- 強気相場でB&H(+35%/年)に勝つのは構造的に困難。ボットの価値はリスク管理
- yfinance 1h データはシステム時刻から730日以内に制限
- Redbubble: Cloudflare Turnstileで自動化不可 → 手動アップロード運用
- Playwright セッション切れ問題 → KDPはEPUB生成のみ・手動アップロード
