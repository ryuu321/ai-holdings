"""
design_gen.py — MidnightTorii スタイルデザイン生成 (Pillow)
テーマ: 日本の夜・神秘・鳥居・狐・月
出力: data/designs/{index:04d}_{type}.png (3000x3000)
"""
import json
import math
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

DATA_DIR   = Path(__file__).parent / "data"
DESIGN_DIR = DATA_DIR / "designs"
STATE_FILE = DATA_DIR / "state.json"

DESIGN_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

SIZE = 3000

# フォント候補（日本語対応）
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansJP-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
]

# MidnightTorii カラーパレット
PALETTES = [
    {"bg": "#050510", "sky": "#0a0820", "moon": "#f5f0dc", "moon_glow": "#d4b87a",
     "torii": "#8b1a1a", "accent": "#c9956a", "text": "#e8e0d0", "name": "midnight_red"},
    {"bg": "#04080f", "sky": "#080d1a", "moon": "#e8f0f8", "moon_glow": "#6a9ab8",
     "torii": "#1a3a5c", "accent": "#4a7fa8", "text": "#d0e0f0", "name": "indigo_night"},
    {"bg": "#080408", "sky": "#120a1a", "moon": "#f0e8f8", "moon_glow": "#9a6ab8",
     "torii": "#4a1a6a", "accent": "#8a4ab0", "text": "#e0d0f0", "name": "purple_mystic"},
    {"bg": "#050a05", "sky": "#080f08", "moon": "#e8f5e8", "moon_glow": "#6ab87a",
     "torii": "#1a4a1a", "accent": "#4a9a5a", "text": "#d0f0d8", "name": "forest_spirit"},
    {"bg": "#0f0804", "sky": "#1a1008", "moon": "#f8f0e0", "moon_glow": "#c8a050",
     "torii": "#6a2a08", "accent": "#c87828", "text": "#f0ddb8", "name": "autumn_flame"},
]

BRAND = "MidnightTorii"


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_stars(draw: ImageDraw.ImageDraw, palette: dict, count: int = 200):
    """星を散りばめる"""
    rng = random.Random(42)
    for _ in range(count):
        x = rng.randint(0, SIZE)
        y = rng.randint(0, SIZE * 2 // 3)
        r = rng.choice([1, 1, 1, 2, 2, 3])
        alpha = rng.randint(120, 255)
        color = f"#{alpha:02x}{alpha:02x}{min(alpha + 20, 255):02x}"
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _draw_moon(draw: ImageDraw.ImageDraw, palette: dict, cx: int, cy: int, r: int):
    """月を描く（グロー付き）"""
    glow_color = palette["moon_glow"]
    for i in range(5, 0, -1):
        gr = r + i * 18
        opacity = 20 + i * 8
        gc = _hex_opacity(glow_color, opacity)
        draw.ellipse([cx - gr, cy - gr, cx + gr, cy + gr], fill=gc)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=palette["moon"])


def _draw_torii(draw: ImageDraw.ImageDraw, palette: dict, cx: int, base_y: int, scale: float = 1.0):
    """鳥居シルエットを描く"""
    color = palette["torii"]
    w = int(500 * scale)
    h = int(700 * scale)
    post_w = int(50 * scale)
    beam_h = int(55 * scale)

    # 柱（左右）
    lx, rx = cx - w // 2, cx + w // 2 - post_w
    draw.rectangle([lx, base_y - h, lx + post_w, base_y], fill=color)
    draw.rectangle([rx, base_y - h, rx + post_w, base_y], fill=color)

    # 笠木（上の梁・反り）
    kasagi_y = base_y - h
    draw.rectangle([cx - w // 2 - 40, kasagi_y, cx + w // 2 + 40, kasagi_y + beam_h], fill=color)
    # 反り（三角）
    for dx in range(-60, 61):
        curve = int(30 * (1 - (dx / 60) ** 2))
        draw.rectangle([cx - w // 2 - 60 + dx, kasagi_y - curve,
                        cx - w // 2 - 59 + dx, kasagi_y], fill=color)
        draw.rectangle([cx + w // 2 + 59 - dx, kasagi_y - curve,
                        cx + w // 2 + 60 - dx, kasagi_y], fill=color)

    # 島木（2段目の梁）
    shimagi_y = kasagi_y + beam_h + int(60 * scale)
    draw.rectangle([cx - w // 2 - 10, shimagi_y, cx + w // 2 + 10, shimagi_y + int(beam_h * 0.7)], fill=color)

    # 貫（横木 中段）
    nuki_y = shimagi_y + int(160 * scale)
    draw.rectangle([cx - w // 2 + post_w, nuki_y, cx + w // 2, nuki_y + int(25 * scale)], fill=color)


def _draw_lantern(draw: ImageDraw.ImageDraw, palette: dict, cx: int, cy: int, scale: float = 1.0):
    """提灯を描く"""
    color = palette["torii"]
    glow = palette["moon_glow"]
    w = int(120 * scale)
    h = int(200 * scale)

    # 本体（楕円）
    for i in range(3, 0, -1):
        gc = _hex_opacity(glow, 30 * i)
        draw.ellipse([cx - w // 2 - i * 10, cy - h // 2 - i * 10,
                      cx + w // 2 + i * 10, cy + h // 2 + i * 10], fill=gc)
    draw.ellipse([cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2], fill=color)
    # 輪（装飾リング）
    ring_color = palette["accent"]
    for ry in [cy - h // 3, cy, cy + h // 3]:
        draw.arc([cx - w // 2, ry - 8, cx + w // 2, ry + 8], 0, 180, fill=ring_color, width=4)
    # 紐
    draw.line([(cx, cy - h // 2 - 60), (cx, cy - h // 2)], fill=ring_color, width=6)


def _draw_text(draw: ImageDraw.ImageDraw, text: str, palette: dict, y_center: int):
    """テキストを中央配置"""
    font_main = _load_font(140)
    font_brand = _load_font(55)

    lines = text.split("\n")
    line_h = 170
    total_h = len(lines) * line_h
    y = y_center - total_h // 2

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_main)
        w = bbox[2] - bbox[0]
        x = (SIZE - w) // 2
        # 影
        draw.text((x + 3, y + 3), line, font=font_main, fill="#00000088")
        draw.text((x, y), line, font=font_main, fill=palette["text"])
        y += line_h

    # ブランド名
    bbox = draw.textbbox((0, 0), BRAND, font=font_brand)
    bw = bbox[2] - bbox[0]
    brand_y = SIZE - 200
    draw.text(((SIZE - bw) // 2, brand_y), BRAND, font=font_brand, fill=palette["accent"])

    # ブランドライン
    lw = 300
    draw.line([(SIZE // 2 - lw, brand_y - 20), (SIZE // 2 + lw, brand_y - 20)],
              fill=palette["accent"], width=2)


def _hex_opacity(hex_color: str, opacity: int) -> str:
    """#rrggbb + opacityを合成した色文字列を返す"""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"#{r:02x}{g:02x}{b:02x}{min(opacity, 255):02x}"


def generate(design: dict, index: int) -> Path:
    palette = random.choice(PALETTES)
    dtype = design.get("type", "torii_moon")

    img = Image.new("RGBA", (SIZE, SIZE), palette["bg"])
    draw = ImageDraw.Draw(img)

    # 夜空グラデーション（上部）
    for y in range(SIZE * 2 // 3):
        alpha = int(80 * (1 - y / (SIZE * 2 / 3)))
        draw.line([(0, y), (SIZE, y)], fill=_hex_opacity(palette["sky"], 80 + alpha))

    # 星
    _draw_stars(draw, palette, count=180)

    # 月は上部・鳥居は最下部・テキストは中央（重なり回避）
    moon_cx    = SIZE // 2
    moon_cy    = SIZE // 7
    moon_r     = 220
    torii_base = SIZE - 80      # 鳥居の足元を画面下端に固定
    text_cy    = SIZE * 55 // 100

    if dtype in ("torii_moon", "torii_night", "torii_fog", "torii_reflection",
                 "mountain_torii", "sakura_torii"):
        _draw_moon(draw, palette, moon_cx, moon_cy, moon_r)
        _draw_torii(draw, palette, SIZE // 2, torii_base, scale=1.3)

    elif dtype in ("moon_fox", "nine_tails", "fox_mask", "fox_festival"):
        _draw_moon(draw, palette, SIZE // 4, moon_cy, moon_r)
        _draw_torii(draw, palette, SIZE * 3 // 4, torii_base, scale=0.85)

    elif dtype in ("lantern", "stone_lantern", "spirit_lantern", "lantern_procession"):
        _draw_moon(draw, palette, moon_cx, moon_cy, 180)
        for i, lx in enumerate([SIZE // 5, SIZE // 2, SIZE * 4 // 5]):
            _draw_lantern(draw, palette, lx, SIZE * 78 // 100, scale=0.7 + i * 0.1)

    elif dtype in ("moon_rabbit", "moon_dragon", "bamboo_moon", "lighthouse_moon",
                   "shrine_snow", "spring_spirit"):
        _draw_moon(draw, palette, SIZE * 3 // 4, moon_cy, moon_r)
        _draw_torii(draw, palette, SIZE // 2, torii_base, scale=1.1)

    else:
        _draw_moon(draw, palette, moon_cx, moon_cy, moon_r)
        _draw_torii(draw, palette, SIZE // 2, torii_base, scale=1.1)

    _draw_text(draw, design["text"], palette, text_cy)

    # RGB変換して保存
    out = img.convert("RGB")
    out_path = DESIGN_DIR / f"{index:04d}_{palette['name']}.png"
    out.save(out_path, "PNG")
    return out_path


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"next_quote_index": 0, "uploaded": []}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def next_design() -> tuple[Path, dict] | tuple[None, None]:
    from quotes import QUOTES
    state = _load_state()
    idx = state["next_quote_index"]
    if idx >= len(QUOTES):
        idx = 0
    design = QUOTES[idx]
    path = generate(design, idx)
    state["next_quote_index"] = idx + 1
    _save_state(state)
    return path, design


if __name__ == "__main__":
    from quotes import QUOTES
    print(f"テスト生成: {len(QUOTES)} デザイン")
    for i in range(3):
        p, d = next_design()
        print(f"  → {p}")
