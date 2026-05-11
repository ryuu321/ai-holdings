"""ゲーム構想 → Phaser.jsコード生成 → HTMLファイル出力"""
import os
import sys
import json
import re
import shutil
from pathlib import Path
from groq import Groq

TEMPLATES_DIR = Path(__file__).parent / "templates"
OUTPUT_DIR    = Path(__file__).parent / "output"

SYSTEM_PROMPT = """You are an expert Phaser.js 3 game developer.
Generate a complete, working Phaser.js 3 game based on the user's concept.

Output ONLY a valid JSON object. No markdown, no explanation, no code fences.
JSON format: {"title": "...", "type": "clicker|quiz|runner", "bg_color": "#xxxxxx", "script": "..."}

STRICT CODING RULES for the "script" field:
1. Use a Phaser.Scene class (not plain functions). Example structure:
   var config = { type: Phaser.AUTO, width: 480, height: 640, backgroundColor: '#1a1a2e', scene: [GameScene] };
   class GameScene extends Phaser.Scene {
     constructor() { super('GameScene'); }
     create() { ... }
     update() { ... }
   }
   new Phaser.Game(config);

2. NEVER use this.add.text() to update scores. Always store text as a variable and call setText():
   this.scoreText = this.add.text(10, 10, 'スコア: 0', {fontSize:'24px', fill:'#fff'});
   // to update: this.scoreText.setText('スコア: ' + score);

3. Use only primitive shapes (rectangles, circles, text). No external image assets.

4. Make interactive elements large enough to click (min 60x60px).

5. Set backgroundColor in the Phaser config (not CSS).

6. All UI text must be in Japanese if concept is in Japanese.

7. The script must be 100% self-contained — no imports, no external files.

8. For clicker: objects to click + score display + simple upgrade or progression.
   For quiz: 4-option buttons + question text + score tracking.
   For runner: auto-scrolling obstacles + jump mechanic + score.
"""

def generate_game(concept: str) -> dict:
    client = Groq(api_key=os.environ["GROQ_API_KEY"])

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"ゲーム構想: {concept}"}
        ],
        temperature=0.7,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content.strip()

    # コードブロックを除去
    raw = re.sub(r'```(?:json)?\s*', '', raw).strip()

    # JSONを抽出（strict=Falseで制御文字を許容）
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        raise ValueError(f"JSON not found in response:\n{raw[:300]}")
    return json.loads(m.group(), strict=False)


def build_html(game_data: dict, game_id: str) -> Path:
    game_type = game_data.get("type", "clicker")
    if game_type not in ("clicker", "quiz", "runner"):
        game_type = "clicker"

    template_path = TEMPLATES_DIR / game_type / "index.html"
    template = template_path.read_text(encoding="utf-8")

    html = (template
        .replace("{{GAME_TITLE}}", game_data["title"])
        .replace("{{BG_COLOR}}", game_data.get("bg_color", "#1a1a2e"))
        .replace("{{GAME_SCRIPT}}", game_data["script"])
    )

    out_dir = OUTPUT_DIR / game_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    concept = os.environ.get("GAME_CONCEPT", "")
    game_id = os.environ.get("GAME_ID", "game")

    if not concept:
        print("ERROR: GAME_CONCEPT が設定されていません")
        sys.exit(1)

    print(f"[game-gen] 生成開始: {concept[:60]}")
    game_data = generate_game(concept)
    print(f"[game-gen] タイプ: {game_data.get('type')}  タイトル: {game_data.get('title')}")

    out_path = build_html(game_data, game_id)
    print(f"[game-gen] 出力: {out_path}")
    print(f"[game-gen] 完了")
