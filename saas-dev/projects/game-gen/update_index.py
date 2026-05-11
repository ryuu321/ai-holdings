"""gh-pagesのゲーム一覧インデックスを更新"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone

pages_dir = Path(sys.argv[1])
game_id   = sys.argv[2]
concept   = sys.argv[3]

index_file = pages_dir / "games" / "index.json"
index = json.loads(index_file.read_text()) if index_file.exists() else {"games": []}

# 既存エントリを更新 or 追加
existing = next((g for g in index["games"] if g["id"] == game_id), None)
entry = {
    "id": game_id,
    "concept": concept,
    "url": f"https://ryuu321.github.io/ai-holdings/games/{game_id}/",
    "created_at": existing.get("created_at", datetime.now(timezone.utc).isoformat()) if existing else datetime.now(timezone.utc).isoformat(),
    "updated_at": datetime.now(timezone.utc).isoformat(),
}
if existing:
    index["games"] = [entry if g["id"] == game_id else g for g in index["games"]]
else:
    index["games"].append(entry)

index_file.parent.mkdir(parents=True, exist_ok=True)
index_file.write_text(json.dumps(index, ensure_ascii=False, indent=2))

# ゲーム一覧HTMLも生成
cards = "\n".join(
    f'<div class="card"><a href="{g["url"]}" target="_blank"><strong>{g["id"]}</strong></a><p>{g["concept"][:50]}</p></div>'
    for g in reversed(index["games"])
)
html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>AI Game Generator</title>
<style>
  body {{ font-family: sans-serif; background: #0f0f1a; color: #eee; padding: 2rem; }}
  h1 {{ color: #7c6fff; }}
  .card {{ background: #1e1e2e; border-radius: 8px; padding: 1rem; margin: 1rem 0; }}
  .card a {{ color: #a0cfff; text-decoration: none; font-size: 1.1rem; }}
  p {{ color: #aaa; margin-top: 0.3rem; }}
</style></head>
<body>
<h1>🎮 AI Game Generator</h1>
<p>ゲーム構想を話すだけで自動生成されたゲーム一覧</p>
{cards}
</body></html>"""

(pages_dir / "games" / "index.html").write_text(html, encoding="utf-8")
print(f"インデックス更新完了: {len(index['games'])}件")
