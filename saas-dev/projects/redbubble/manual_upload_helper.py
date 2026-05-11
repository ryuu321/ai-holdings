"""
manual_upload_helper.py — MidnightTorii 手動アップロードヘルパー

使い方:
  python manual_upload_helper.py          # 次の5件を処理
  python manual_upload_helper.py --batch 3  # 3件ずつ処理
"""
import io
import json
import os
import subprocess
import sys
from pathlib import Path

# Windows CP932 端末でも日本語・記号を出力できるよう UTF-8 に切り替え
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stdin  = io.TextIOWrapper(sys.stdin.buffer,  encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from quotes import DESIGNS
from design_gen import generate

BATCH_SIZE  = 5
DATA_DIR    = Path(__file__).parent / "data"
DESIGNS_DIR = DATA_DIR / "designs"
STATE_FILE  = DATA_DIR / "state.json"
UPLOAD_URL  = "https://www.redbubble.com/portfolio/images/new"


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"next_quote_index": 0, "uploaded": []}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def make_title(design: dict) -> str:
    return design.get("title_en", design["text"].split("\n")[0].strip() + " — MidnightTorii")


def make_main_tag(design: dict) -> str:
    return design["tags"][0]


def make_supporting_tags(design: dict) -> str:
    return ", ".join(design["tags"][1:14])


def make_description(design: dict) -> str:
    text = design["text"].replace("\n", " / ").strip()
    return (
        f"{text}\n\n"
        "MidnightTorii — Dark, mystical Japanese art. "
        "Moonlit torii gates, kitsune foxes, and glowing lanterns.\n\n"
        "Perfect for notebooks, laptops, water bottles, phone cases and more."
    )


def get_or_generate(index: int, design: dict) -> Path:
    """既存画像があれば流用、なければ生成"""
    existing = sorted(DESIGNS_DIR.glob(f"{index:04d}_*.png"))
    if existing:
        return existing[0]
    print(f"  生成中: デザイン #{index + 1}...", flush=True)
    return generate(design, index)


def open_url(url: str):
    if sys.platform == "win32":
        os.startfile(url)
    elif sys.platform == "darwin":
        subprocess.run(["open", url])
    else:
        subprocess.run(["xdg-open", url])


def open_folder(path: Path):
    if sys.platform == "win32":
        subprocess.run(["explorer", str(path)])
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)])


def separator(char="─", width=62):
    print(char * width)


def box(label: str, content: str):
    separator()
    print(f"  [{label}]")
    separator()
    for line in content.split("\n"):
        print(f"  {line}")
    separator()
    print()


def main():
    batch_size = BATCH_SIZE
    if "--batch" in sys.argv:
        try:
            batch_size = int(sys.argv[sys.argv.index("--batch") + 1])
        except (ValueError, IndexError):
            pass

    state = load_state()
    start = state.get("next_quote_index", 0)
    total = len(DESIGNS)

    if start >= total:
        start = 0  # ループ

    DESIGNS_DIR.mkdir(parents=True, exist_ok=True)

    # バッチ作成
    end = min(start + batch_size, total)
    batch = []
    for idx in range(start, end):
        design = DESIGNS[idx]
        img_path = get_or_generate(idx, design)
        batch.append((idx, design, img_path))

    # ヘッダー
    print()
    separator("=")
    print("  MidnightTorii — 手動アップロードヘルパー")
    separator("=")
    print(f"  対象: {len(batch)} 件 (#{start + 1} 〜 #{end})")
    print(f"  残り: {total - end} 件")
    print()
    print("  ブラウザ（アップロードページ）とフォルダを開きます...")
    open_url(UPLOAD_URL)
    open_folder(DESIGNS_DIR)
    print()
    input("  準備できたら Enter を押してください > ")
    print()

    for i, (idx, design, img_path) in enumerate(batch, 1):
        separator("=")
        print(f"  デザイン {i} / {len(batch)}  (全体 #{idx + 1} / {total})")
        separator("=")
        print()

        # 画像ファイル
        separator()
        print(f"  [画像ファイル]  {img_path.name}")
        print(f"  フォルダ: {img_path.parent}")
        separator()
        print()

        # Title
        box("Title (required)", make_title(design))

        # Main Tag
        box("Main Tag", make_main_tag(design))

        # Supporting Tags
        box("Supporting Tags", make_supporting_tags(design))

        # Description
        box("Description", make_description(design))

        if i < len(batch):
            input("  アップロード完了したら Enter（次のデザインへ）> ")
            open_url(UPLOAD_URL)
            print()
        else:
            print()
            input("  最後のデザインをアップロードしたら Enter > ")

    # 完了処理
    print()
    separator("=")
    answer = input(f"  全 {len(batch)} 件アップロード完了しましたか？ [y/n/数字] > ").strip().lower()

    done_count = 0
    if answer == "y":
        done_count = len(batch)
    elif answer.isdigit():
        done_count = min(int(answer), len(batch))

    if done_count > 0:
        new_idx = start + done_count
        if new_idx >= total:
            new_idx = 0
        state["next_quote_index"] = new_idx
        uploaded = state.get("uploaded", [])
        uploaded.extend(batch[j][0] for j in range(done_count))
        state["uploaded"] = uploaded
        save_state(state)
        print()
        print(f"  記録しました: {done_count} 件完了")
        print(f"  次回実行時は #{new_idx + 1} から")
    else:
        print("  state は更新しませんでした")

    print()
    separator("=")
    print("  お疲れ様でした！")
    separator("=")
    print()


if __name__ == "__main__":
    main()
