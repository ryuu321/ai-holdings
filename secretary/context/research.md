---
company: research
updated: 2026-05-01
---

## 稼働中
- 市場リサーチ（CSO配下）
- 毎朝JST7時自動実行
- 出力: `research/output/YYYY-MM-DD_report.md` + `_opportunity.md`
- ventures.mdへ自動追記

## モデル
- gemini-flash-latest（SDK移行済み）

## 重要パス
- スクリプト: `research/research_daily.py`
- 事業候補: `secretary/knowledge/ventures.md`
