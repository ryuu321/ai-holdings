"""EPUB + カバー画像生成"""
import random
import math
from pathlib import Path
from ebooklib import epub
from PIL import Image, ImageDraw, ImageFont


# カテゴリ別テーマ
CATEGORY_THEMES = {
    "美容・コスメ": {
        "bg": [("#4a0e3a", "#c2185b"), ("#1a0a2e", "#e91e8c"), ("#2d0a4e", "#ad1457")],
        "accent": "#ffd700", "badge": "美容 BEAUTY",
    },
    "投資・資産形成": {
        "bg": [("#0a1628", "#1a3a5c"), ("#0d1f3c", "#0f3460"), ("#071526", "#1b4980")],
        "accent": "#00d4aa", "badge": "投資 FINANCE",
    },
    "投資・シニア向け": {
        "bg": [("#0a1628", "#1a3a5c"), ("#0d1f3c", "#0f3460"), ("#071526", "#1b4980")],
        "accent": "#00d4aa", "badge": "投資 FINANCE",
    },
    "節約・家計管理": {
        "bg": [("#1a2e0a", "#2e7d32"), ("#0d2b1a", "#388e3c"), ("#072616", "#43a047")],
        "accent": "#ffeb3b", "badge": "節約 MONEY",
    },
    "節約・ふるさと納税": {
        "bg": [("#1a2e0a", "#2e7d32"), ("#0d2b1a", "#388e3c"), ("#072616", "#43a047")],
        "accent": "#ffeb3b", "badge": "節約 MONEY",
    },
    "節約・一人暮らし": {
        "bg": [("#1a2e0a", "#2e7d32"), ("#0d2b1a", "#388e3c"), ("#072616", "#43a047")],
        "accent": "#ffeb3b", "badge": "節約 MONEY",
    },
    "副業・収入アップ": {
        "bg": [("#1a1a2e", "#283593"), ("#0f1535", "#1565c0"), ("#0a1020", "#1976d2")],
        "accent": "#ffab40", "badge": "副業 SIDE",
    },
    "副業・スマホ": {
        "bg": [("#1a1a2e", "#283593"), ("#0f1535", "#1565c0"), ("#0a1020", "#1976d2")],
        "accent": "#ffab40", "badge": "副業 SIDE",
    },
    "副業・Kindle出版": {
        "bg": [("#1a1a2e", "#283593"), ("#0f1535", "#1565c0"), ("#0a1020", "#1976d2")],
        "accent": "#ffab40", "badge": "副業 SIDE",
    },
    "副業・物販": {
        "bg": [("#1a1a2e", "#283593"), ("#0f1535", "#1565c0"), ("#0a1020", "#1976d2")],
        "accent": "#ffab40", "badge": "物販 SELL",
    },
    "健康・フィットネス": {
        "bg": [("#0a2e1a", "#1b5e20"), ("#0d2b1a", "#2e7d32"), ("#072616", "#388e3c")],
        "accent": "#a5d6a7", "badge": "健康 HEALTH",
    },
    "健康・睡眠": {
        "bg": [("#0a1a2e", "#1a237e"), ("#0d1f3c", "#283593"), ("#071526", "#303f9f")],
        "accent": "#b3e5fc", "badge": "睡眠 SLEEP",
    },
    "ダイエット・健康": {
        "bg": [("#2e0a1a", "#880e4f"), ("#1a0514", "#ad1457"), ("#2a0a28", "#c2185b")],
        "accent": "#f48fb1", "badge": "ダイエット DIET",
    },
    "IT・AI活用": {
        "bg": [("#0a0a1a", "#1a237e"), ("#050510", "#0d47a1"), ("#000008", "#1565c0")],
        "accent": "#40c4ff", "badge": "AI TECH",
    },
    "IT・スキルアップ": {
        "bg": [("#0a0a1a", "#1a237e"), ("#050510", "#0d47a1"), ("#000008", "#1565c0")],
        "accent": "#40c4ff", "badge": "IT TECH",
    },
    "仕事術・生産性": {
        "bg": [("#1a1a0a", "#f57f17"), ("#1a1000", "#e65100"), ("#0a0800", "#bf360c")],
        "accent": "#fff176", "badge": "仕事術 WORK",
    },
    "ライフスタイル・ミニマリズム": {
        "bg": [("#1a1a1a", "#424242"), ("#111111", "#616161"), ("#0a0a0a", "#757575")],
        "accent": "#e0e0e0", "badge": "生活 LIFE",
    },
    "メンタル・心理": {
        "bg": [("#1a0a2e", "#4a148c"), ("#110520", "#6a1b9a"), ("#0a0318", "#7b1fa2")],
        "accent": "#ce93d8", "badge": "メンタル MIND",
    },
    "介護・シニア": {
        "bg": [("#1a2e1a", "#2e7d32"), ("#0f1f0f", "#388e3c"), ("#080f08", "#43a047")],
        "accent": "#a5d6a7", "badge": "介護 CARE",
    },
    "教育費・マネー": {
        "bg": [("#1a1a0a", "#827717"), ("#14140a", "#9e8a00"), ("#0a0a05", "#b8a000")],
        "accent": "#fff59d", "badge": "教育 EDU",
    },
    "default": {
        "bg": [("#0f0c29", "#302b63"), ("#1a1a2e", "#16213e"), ("#0d0d1a", "#1a237e")],
        "accent": "#e0e0e0", "badge": "実用 GUIDE",
    },
}


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _gradient(img, color_top, color_bottom):
    """縦グラデーション"""
    w, h = img.size
    r1, g1, b1 = _hex_to_rgb(color_top)
    r2, g2, b2 = _hex_to_rgb(color_bottom)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))


def _draw_decorations(draw, w, h, accent):
    """幾何学的な装飾要素"""
    ac = _hex_to_rgb(accent)

    # 右上の大円（透過感）
    for r in range(320, 0, -40):
        alpha = int(15 + (320 - r) * 0.08)
        color = (min(ac[0]+30, 255), min(ac[1]+30, 255), min(ac[2]+30, 255), alpha)
        draw.ellipse([w - r, -r, w + r, r], outline=(*ac, alpha), width=2)

    # 左下の小円群
    for r in range(180, 0, -30):
        alpha = int(10 + (180 - r) * 0.1)
        draw.ellipse([-r, h - r*2 + r, r, h + r], outline=(*ac, alpha), width=2)

    # 斜めのアクセントライン
    for offset in range(0, 80, 20):
        draw.line([(0, h//2 - 60 + offset), (w, h//2 - 20 + offset)],
                  fill=(*ac, 30), width=1)

    # 上部・下部の太いアクセントバー
    draw.rectangle([0, 220, w, 228], fill=accent)
    draw.rectangle([80, 236, w - 80, 240], fill=(*ac, 120))
    draw.rectangle([0, h - 228, w, h - 220], fill=accent)
    draw.rectangle([80, h - 240, w - 80, h - 236], fill=(*ac, 120))

    # タイトルエリアの背景パネル
    panel_top = h // 2 - 360
    panel_bot = h // 2 + 320
    draw.rectangle([60, panel_top, w - 60, panel_bot],
                   fill=(0, 0, 0, 80), outline=(*ac, 60), width=3)


def _find_font():
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
            ImageFont.truetype(fp, 10)
            return fp
        except Exception:
            continue
    return None


def make_cover(title: str, output_path: Path, category: str = "default") -> Path:
    w, h = 1600, 2560
    theme = CATEGORY_THEMES.get(category, CATEGORY_THEMES["default"])
    bg_top, bg_bottom = random.choice(theme["bg"])
    accent = theme["accent"]
    badge = theme["badge"]

    img = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    _gradient(img, bg_top, bg_bottom)

    draw = ImageDraw.Draw(img, "RGBA")
    _draw_decorations(draw, w, h, accent)

    font_path = _find_font()
    def font(size):
        if font_path:
            return ImageFont.truetype(font_path, size)
        return ImageFont.load_default(size=size)

    # バッジ（カテゴリラベル）
    badge_font = font(44)
    bx, by = 120, 120
    bbox = draw.textbbox((0, 0), badge, font=badge_font)
    bw = bbox[2] - bbox[0] + 40
    draw.rectangle([bx - 20, by - 10, bx + bw, by + 54], fill=accent)
    draw.text((bx, by), badge, font=badge_font, fill="#000000")

    # タイトル（中央・大きく）- 幅に収まる最大フォントサイズを自動計算
    max_w = w - 200  # 左右マージン各100px
    for font_size in range(180, 60, -10):
        title_font = font(font_size)
        bbox = draw.textbbox((0, 0), title, font=title_font)
        if bbox[2] - bbox[0] <= max_w:
            break
    # 1行に収まるなら1行、収まらなければ2分割
    bbox = draw.textbbox((0, 0), title, font=title_font)
    if bbox[2] - bbox[0] <= max_w:
        lines = [title]
    else:
        mid = len(title) // 2
        lines = [title[:mid], title[mid:]]
    line_h = font_size + 40
    total_h = len(lines) * line_h
    y = h // 2 - total_h // 2
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) // 2 + 6, y + 6), line, font=title_font, fill=(0, 0, 0, 160))
        draw.text(((w - tw) // 2, y), line, font=title_font, fill="#ffffff")
        y += line_h

    # アクセントカラーの下線
    draw.rectangle([160, y + 20, w - 160, y + 28], fill=accent)

    # サブコピー（購買意欲を上げるフレーズ）
    sub_font = font(58)
    sub = "完全解説・今すぐ使える実践ガイド"
    bbox = draw.textbbox((0, 0), sub, font=sub_font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) // 2, y + 60), sub, font=sub_font, fill=accent)

    # 下部の帯
    draw.rectangle([0, h - 200, w, h], fill=(0, 0, 0, 180))
    bottom_font = font(48)
    bottom_text = "読むだけでわかる  保存版"
    bbox = draw.textbbox((0, 0), bottom_text, font=bottom_font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) // 2, h - 140), bottom_text, font=bottom_font, fill="#cccccc")

    cover_path = output_path / "cover.jpg"
    img.convert("RGB").save(cover_path, "JPEG", quality=92)
    return cover_path


def build_epub(book_data: dict, output_dir: Path) -> Path:
    title = book_data["title"]
    category = book_data.get("category", "default")
    output_dir.mkdir(parents=True, exist_ok=True)

    book = epub.EpubBook()
    book.set_identifier(f"kdp-{hash(title) % 99999:05d}")
    book.set_title(title)
    book.set_language("ja")
    book.add_author(book_data.get("author", "山田太郎"))

    # カバー
    cover_path = make_cover(title, output_dir, category)
    with open(cover_path, "rb") as f:
        cover_data = f.read()
    book.set_cover("cover.jpg", cover_data)

    # スタイル
    style = epub.EpubItem(
        uid="style",
        file_name="style.css",
        media_type="text/css",
        content="""
body { font-family: serif; line-height: 1.8; margin: 2em; }
h1 { font-size: 1.8em; border-bottom: 2px solid #333; padding-bottom: 0.3em; }
h2 { font-size: 1.4em; margin-top: 1.5em; }
p { text-indent: 1em; margin: 0.5em 0; }
""",
    )
    book.add_item(style)

    chapters_epub = []

    # 目次ページ
    toc_content = f"<h1>{title}</h1><h2>目次</h2><ol>"
    for i, ch in enumerate(book_data["chapters"], 1):
        toc_content += f"<li>{ch['title']}</li>"
    toc_content += "</ol>"
    toc_page = epub.EpubHtml(title="目次", file_name="toc.xhtml", lang="ja")
    toc_page.content = toc_content
    toc_page.add_item(style)
    book.add_item(toc_page)
    chapters_epub.append(toc_page)

    # 各章
    for i, ch in enumerate(book_data["chapters"], 1):
        c = epub.EpubHtml(title=ch["title"], file_name=f"ch{i:02d}.xhtml", lang="ja")
        content = ch["content"]
        if not content.startswith("<"):
            content = "".join(f"<p>{p}</p>" for p in content.split("\n") if p.strip())
        c.content = f"<h1>{ch['title']}</h1>{content}"
        c.add_item(style)
        book.add_item(c)
        chapters_epub.append(c)

    book.toc = [epub.Link(c.file_name, c.title, c.id) for c in chapters_epub]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters_epub

    safe_title = "".join(c for c in title if c.isalnum() or c in "ー・").replace(" ", "_")[:40]
    epub_path = output_dir / f"{safe_title}.epub"
    epub.write_epub(str(epub_path), book)
    print(f"  EPUB作成: {epub_path}")
    return epub_path
