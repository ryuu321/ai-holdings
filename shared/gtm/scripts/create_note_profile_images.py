"""
TextSeries note.comプロフィール画像生成
- icon.png    400x400  アイコン
- header.png  1500x500 ヘッダー
出力: shared/gtm/content/note/profile/
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace') if hasattr(sys.stdout, 'reconfigure') else None

OUT_DIR = Path(__file__).parent.parent.parent / "gtm" / "content" / "note" / "profile"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FONT_GOTHIC = "C:/Windows/Fonts/BIZ-UDGothicB.ttc"
FONT_MINCHO = "C:/Windows/Fonts/yumin.ttf"

# カラーパレット
BG_DARK   = (15,  20,  40)   # ネイビー
BG_MID    = (25,  35,  70)
ACCENT    = (80, 160, 255)    # ブルー
WHITE     = (255, 255, 255)
GRAY      = (160, 170, 200)


def _font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def make_icon():
    """400x400 アイコン: ロゴマーク風"""
    img = Image.new("RGB", (400, 400), BG_DARK)
    draw = ImageDraw.Draw(img)

    # グラデーション風の角丸背景（近似）
    for i in range(200):
        ratio = i / 200
        r = int(BG_DARK[0] + (BG_MID[0] - BG_DARK[0]) * ratio)
        g = int(BG_DARK[1] + (BG_MID[1] - BG_DARK[1]) * ratio)
        b = int(BG_DARK[2] + (BG_MID[2] - BG_DARK[2]) * ratio)
        draw.rectangle([0, i * 2, 400, i * 2 + 2], fill=(r, g, b))

    # アクセントライン（上部）
    draw.rectangle([40, 60, 360, 64], fill=ACCENT)

    # メインテキスト "Text"
    f_large = _font(FONT_GOTHIC, 88)
    draw.text((200, 155), "Text", font=f_large, fill=WHITE, anchor="mm")

    # サブテキスト "Series"
    f_mid = _font(FONT_GOTHIC, 52)
    draw.text((200, 235), "Series", font=f_mid, fill=ACCENT, anchor="mm")

    # サブテキスト "AI業務ツール"
    f_small = _font(FONT_GOTHIC, 26)
    draw.text((200, 300), "AI業務ツール", font=f_small, fill=GRAY, anchor="mm")

    # アクセントライン（下部）
    draw.rectangle([40, 336, 360, 340], fill=ACCENT)

    out = OUT_DIR / "icon.png"
    img.save(out)
    print(f"✓ アイコン: {out}")
    return out


def make_header():
    """1500x500 ヘッダー: バナー風"""
    img = Image.new("RGB", (1500, 500), BG_DARK)
    draw = ImageDraw.Draw(img)

    # 横グラデーション
    for x in range(1500):
        ratio = x / 1500
        r = int(BG_DARK[0] + (BG_MID[0] - BG_DARK[0]) * ratio * 1.5)
        g = int(BG_DARK[1] + (BG_MID[1] - BG_DARK[1]) * ratio * 1.5)
        b = int(BG_DARK[2] + (BG_MID[2] - BG_DARK[2]) * ratio * 0.8)
        r, g, b = min(r, 255), min(g, 255), min(b, 255)
        draw.line([(x, 0), (x, 500)], fill=(r, g, b))

    # アクセントライン
    draw.rectangle([0, 0, 1500, 5], fill=ACCENT)

    # メインコピー
    f_main = _font(FONT_GOTHIC, 68)
    draw.text((750, 175), "中小企業の書類作成を、", font=f_main, fill=WHITE, anchor="mm")
    draw.text((750, 260), "AIで10倍速く。", font=f_main, fill=ACCENT, anchor="mm")

    # サブコピー
    f_sub = _font(FONT_GOTHIC, 30)
    draw.text((750, 345), "社労士・税理士・不動産など103業種対応", font=f_sub, fill=GRAY, anchor="mm")

    # ブランド名（右下）
    f_brand = _font(FONT_GOTHIC, 28)
    draw.text((1430, 460), "TextSeries", font=f_brand, fill=ACCENT, anchor="rm")

    # アクセントライン（下）
    draw.rectangle([0, 495, 1500, 500], fill=ACCENT)

    out = OUT_DIR / "header.png"
    img.save(out)
    print(f"✓ ヘッダー: {out}")
    return out


if __name__ == "__main__":
    make_icon()
    make_header()
    print(f"\n出力先: {OUT_DIR}")
