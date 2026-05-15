"""
video_generator.py
Pillowで縦型動画フレームを生成 → ffmpegでMP4化
YouTube Shorts (1080x1920, 60秒以内)
"""
import os
import subprocess
import textwrap
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

W, H = 1080, 1920
FRAME_DUR = 7  # 各スライドの秒数
FPS = 30

BG_DARK  = (15, 52, 96)    # #0f3460
BG_MID   = (22, 33, 62)    # #16213e
GOLD     = (245, 166, 35)  # #f5a623
WHITE    = (255, 255, 255)
GRAY     = (180, 180, 200)


def _get_font(size: int, bold: bool = False) -> "ImageFont.FreeTypeFont":
    """フォントを取得（システムフォントにフォールバック）"""
    candidates = [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _draw_wrapped_text(draw: "ImageDraw.Draw", text: str, x: int, y: int,
                       font, fill, max_width: int, line_spacing: int = 8) -> int:
    """折り返しテキストを描画。戻り値: 次のy座標"""
    words = text.split()
    lines = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))

    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        bbox = draw.textbbox((0, 0), line, font=font)
        y += (bbox[3] - bbox[1]) + line_spacing
    return y


def _make_title_frame(title: str, subtitle: str) -> "Image.Image":
    img = Image.new("RGB", (W, H), BG_DARK)
    draw = ImageDraw.Draw(img)

    # グラデーション風オーバーレイ
    for i in range(H // 2):
        alpha = int(255 * (i / (H // 2)) * 0.3)
        draw.line([(0, i), (W, i)], fill=(22, 33, 62))

    # アクセントライン
    draw.rectangle([60, H // 3 - 10, W - 60, H // 3 - 6], fill=GOLD)

    # タイトル
    font_title = _get_font(72, bold=True)
    font_sub   = _get_font(44)
    font_brand = _get_font(36)

    pad = 80
    y = H // 4
    y = _draw_wrapped_text(draw, title, pad, y, font_title, WHITE, W - pad * 2, 12)

    y += 30
    _draw_wrapped_text(draw, subtitle, pad, y, font_sub, GRAY, W - pad * 2)

    # ブランド
    draw.text((pad, H - 120), "AI Holdings", font=font_brand, fill=GOLD)
    draw.text((pad, H - 75), "ryuu321.github.io/ai-holdings", font=_get_font(28), fill=GRAY)

    return img


def _make_prompt_frame(number: int, prompt_title: str, prompt_text: str) -> "Image.Image":
    img = Image.new("RGB", (W, H), BG_MID)
    draw = ImageDraw.Draw(img)

    # 番号バッジ
    badge_r = 65
    draw.ellipse([60, 80, 60 + badge_r * 2, 80 + badge_r * 2], fill=GOLD)
    font_num = _get_font(72, bold=True)
    draw.text((60 + badge_r - 22, 80 + badge_r - 38), str(number), font=font_num, fill=(0, 0, 0))

    # プロンプトタイトル
    font_ptitle = _get_font(54, bold=True)
    font_ptext  = _get_font(38)
    font_label  = _get_font(32)

    y = 230
    y = _draw_wrapped_text(draw, prompt_title, 60, y, font_ptitle, WHITE, W - 120, 10)

    # 区切り線
    y += 24
    draw.rectangle([60, y, W - 60, y + 3], fill=GOLD)
    y += 28

    # プロンプトテキスト（コードスタイル背景）
    wrapped = textwrap.fill(prompt_text, width=38)
    prompt_h = len(wrapped.splitlines()) * 48 + 40
    draw.rounded_rectangle([40, y, W - 40, y + prompt_h], radius=16, fill=(10, 30, 70))
    draw.text((60, y + 20), "PROMPT →", font=font_label, fill=GOLD)
    y2 = y + 70
    for line in wrapped.splitlines():
        draw.text((60, y2), line, font=_get_font(34), fill=(200, 220, 255))
        y2 += 46

    return img


def _make_cta_frame(product_name: str, product_url: str, free_link: str) -> "Image.Image":
    img = Image.new("RGB", (W, H), BG_DARK)
    draw = ImageDraw.Draw(img)

    font_big  = _get_font(80, bold=True)
    font_med  = _get_font(52)
    font_sml  = _get_font(40)
    font_url  = _get_font(36)

    # アクセントバー
    draw.rectangle([0, H // 2 - 8, W, H // 2 + 8], fill=GOLD)

    draw.text((60, 200), "Want 50 more?", font=font_big, fill=WHITE)
    y = 340
    y = _draw_wrapped_text(draw, product_name, 60, y, font_med, GOLD, W - 120)
    y += 24
    y = _draw_wrapped_text(draw, "50 prompts · Instant download · $39", 60, y, font_sml, GRAY, W - 120)

    y = H // 2 + 60
    draw.text((60, y), "Get it on Gumroad:", font=font_sml, fill=WHITE)
    y += 60
    draw.text((60, y), product_url.replace("https://", ""), font=font_url, fill=GOLD)
    y += 80
    draw.text((60, y), "Free prompts & guides:", font=font_sml, fill=WHITE)
    y += 60
    draw.text((60, y), free_link.replace("https://", ""), font=font_url, fill=GRAY)

    return img


def generate_video(
    title: str,
    subtitle: str,
    prompts: list[dict],  # [{"title": str, "text": str}, ...]
    product_name: str,
    product_url: str,
    output_path: Path,
    free_link: str = "ryuu321.github.io/ai-holdings/start.html",
) -> bool:
    """フレームPNGを生成してffmpegでMP4化。成功でTrue。"""
    if not PIL_AVAILABLE:
        print("  [SKIP] Pillow未インストール: pip install Pillow")
        return False

    tmp_dir = output_path.parent / "_frames_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    frames: list[tuple["Image.Image", int]] = []

    # タイトルスライド
    frames.append((_make_title_frame(title, subtitle), FRAME_DUR + 2))

    # プロンプトスライド (最大5枚)
    for i, p in enumerate(prompts[:5], 1):
        frames.append((_make_prompt_frame(i, p["title"], p["text"]), FRAME_DUR))

    # CTAスライド
    frames.append((_make_cta_frame(product_name, product_url, free_link), FRAME_DUR + 3))

    # フレーム保存
    frame_paths = []
    for idx, (frame, dur) in enumerate(frames):
        for f in range(dur * FPS):
            fname = tmp_dir / f"frame_{idx:02d}_{f:04d}.png"
            frame.save(fname)
            frame_paths.append(fname)

    # ffmpegでMP4化
    concat_file = tmp_dir / "frames.txt"
    concat_file.write_text(
        "\n".join(f"file '{p.absolute()}'" for p in frame_paths),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-vf", f"fps={FPS},scale={W}:{H}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    # クリーンアップ
    for f in frame_paths:
        try:
            f.unlink()
        except Exception:
            pass
    try:
        concat_file.unlink()
        tmp_dir.rmdir()
    except Exception:
        pass

    if result.returncode != 0:
        print(f"  [ffmpeg ERROR] {result.stderr[-500:]}")
        return False

    print(f"  動画生成完了: {output_path.name} ({output_path.stat().st_size // 1024}KB)")
    return True
