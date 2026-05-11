"""
PDF使い方ガイド画像を生成（Pillow使用）
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

CATEGORY_COLORS = {
    "節約・家計管理":         ("#1a2e0a", "#2e7d32", "#ffeb3b"),
    "投資・資産形成":         ("#0a1628", "#0f3460", "#00d4aa"),
    "AI副業・ChatGPT活用系":  ("#0a0a1a", "#1565c0", "#40c4ff"),
    "仕事術・生産性":         ("#1a1a0a", "#e65100", "#fff176"),
    "就活・転職・キャリア系":  ("#1a0a2e", "#6a1b9a", "#ce93d8"),
    "default":               ("#0f0c29", "#302b63", "#e0e0e0"),
}


def _find_font(size: int):
    candidates = [
        "C:/Windows/Fonts/YuGothB.ttc",
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    ]
    for fp in candidates:
        try:
            return ImageFont.truetype(fp, size)
        except Exception:
            continue
    return ImageFont.load_default(size=size)


def _wrap(text: str, max_chars: int) -> list:
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= max_chars or ch in "。、\n":
            lines.append(cur.strip())
            cur = ""
    if cur.strip():
        lines.append(cur.strip())
    return lines


def build(template_data: dict, output_dir: Path) -> Path:
    genre = template_data.get("genre", "default")
    bg_top, bg_bot, accent = CATEGORY_COLORS.get(genre, CATEGORY_COLORS["default"])

    w, h = 1200, 1700
    img = Image.new("RGB", (w, h), bg_top)
    draw = ImageDraw.Draw(img)

    # グラデーション背景
    from PIL import ImageDraw as ID
    for y in range(h):
        t = y / h
        r1, g1, b1 = int(bg_top[1:3], 16), int(bg_top[3:5], 16), int(bg_top[5:7], 16)
        r2, g2, b2 = int(bg_bot[1:3], 16), int(bg_bot[3:5], 16), int(bg_bot[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # ヘッダーバー
    draw.rectangle([0, 0, w, 110], fill=(0, 0, 0, 0))
    draw.rectangle([0, 108, w, 114], fill=accent)

    # タイトル
    fn_title = _find_font(54)
    name = template_data.get("name", "テンプレート")
    bb = draw.textbbox((0, 0), name, font=fn_title)
    draw.text(((w - (bb[2] - bb[0])) // 2, 28), name, font=fn_title, fill="#ffffff")

    # 価格バッジ
    price = template_data.get("price", 500)
    fn_badge = _find_font(40)
    draw.rectangle([w - 190, 24, w - 20, 88], fill=accent)
    draw.text((w - 175, 36), f"¥{price}", font=fn_badge, fill="#000000")

    y = 135
    fn_h2   = _find_font(42)
    fn_body = _find_font(32)
    fn_sm   = _find_font(28)
    guide   = template_data.get("guide", {})

    def section(icon_title: str, items: list, is_steps: bool = False):
        nonlocal y
        draw.text((50, y), icon_title, font=fn_h2, fill=accent)
        y += 60
        for i, item in enumerate(items, 1):
            prefix = f"  {i}. " if is_steps else "  ✓ "
            for line in _wrap(prefix + item, 36):
                draw.text((70, y), line, font=fn_body if is_steps else fn_sm,
                          fill="#ffffff" if is_steps else "#ccddff")
                y += 46
        y += 16
        draw.rectangle([50, y, w - 50, y + 2], fill=accent)
        y += 20

    # 概要
    draw.text((50, y), "📌 概要", font=fn_h2, fill=accent)
    y += 58
    for line in _wrap(guide.get("overview", ""), 36):
        draw.text((70, y), line, font=fn_body, fill="#e0e0e0")
        y += 46
    y += 10
    draw.rectangle([50, y, w - 50, y + 2], fill=accent)
    y += 20

    section("🚀 使い方", guide.get("steps", []), is_steps=True)
    section("💡 活用ポイント", guide.get("tips", []), is_steps=False)

    # フッター
    draw.rectangle([0, h - 70, w, h], fill=(0, 0, 0))
    draw.text((50, h - 50), "AI Holdings D.ryu  /  note & Gumroad", font=fn_sm, fill="#888888")

    out = output_dir / "guide.jpg"
    img.save(str(out), "JPEG", quality=90)
    return out
