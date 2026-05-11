"""
ventures/digital_templates/main.py
週次実行: テンプレート生成 → Gumroad登録 → note記事で紹介 → Gemini最適化
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.optimizer import optimize
from shared.metrics import load_state, save_state, record_performance, apply_optimization
from generator import pick_next, generate, build_csv
from guide_builder import build
from publisher import gumroad_create_product, gumroad_upload_file, post_note_promotion

STATE_PATH  = Path(__file__).parent / "state.json"
OUTPUT_DIR  = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

DEFAULT_STATE = {
    "venture": "digital_templates",
    "params": {
        "templates_per_run": 2,
        "priority_genres": [],
        "note_account_id": 1,
    },
    "performance_history": [],
    "learnings": [],
    "last_optimized": None,
    "generated_names": [],
    "products": [],
    "templates_published": 0,
}


def main():
    print(f"\n{'='*50}")
    print("[digital_templates] テンプレート生成・販売 開始")
    state = load_state(STATE_PATH) or DEFAULT_STATE
    params = state.get("params", DEFAULT_STATE["params"])
    per_run = params.get("templates_per_run", 2)

    published_count = 0
    revenue_estimate = 0

    for i in range(per_run):
        print(f"\n--- テンプレート {i+1}/{per_run} ---")
        category = pick_next(state.get("generated_names", []), params)
        if not category:
            print("  全カテゴリ生成済み。リセットして再生成します。")
            state["generated_names"] = []
            category = pick_next([], params)

        print(f"  カテゴリ: {category['name']} (¥{category['price']})")

        # Step1: コンテンツ生成
        try:
            template_data = generate(category, params)
        except Exception as e:
            print(f"  [ERROR] 生成失敗: {e}")
            continue

        # Step2: 出力ディレクトリ
        safe_name = "".join(c for c in category["name"] if c.isalnum() or c in "ー・")[:20]
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        item_dir = OUTPUT_DIR / f"{date_str}_{safe_name}"
        item_dir.mkdir(exist_ok=True)

        # Step3: CSVビルド
        csv_data = build_csv(template_data)
        csv_path = item_dir / f"{safe_name}.csv"
        csv_path.write_bytes(csv_data)
        print(f"  CSV生成: {csv_path.name}")

        # Step4: ガイド画像ビルド
        try:
            guide_path = build(template_data, item_dir)
            print(f"  ガイド画像生成: {guide_path.name}")
        except Exception as e:
            print(f"  [WARN] ガイド画像生成失敗: {e}")
            guide_path = None

        # Step5: Gumroad登録
        gumroad_result = gumroad_create_product(
            template_data["name"],
            template_data.get("gumroad_description", ""),
            template_data.get("price", category["price"])
        )
        if gumroad_result:
            print(f"  Gumroad登録: {gumroad_result['url']}")
            gumroad_upload_file(gumroad_result["id"], csv_path)
            if guide_path:
                gumroad_upload_file(gumroad_result["id"], guide_path)
            gumroad_url = gumroad_result["url"]
        else:
            gumroad_url = "（Gumroad未設定）"

        # Step6: note記事で紹介
        note_url = post_note_promotion(
            template_data, gumroad_url,
            account_id=params.get("note_account_id", 1)
        )
        if note_url:
            print(f"  note紹介記事: {note_url}")

        # 記録
        state.setdefault("generated_names", []).append(category["name"])
        state.setdefault("products", []).append({
            "date": date_str,
            "name": category["name"],
            "price": category["price"],
            "gumroad_url": gumroad_url,
            "note_url": note_url,
        })
        state["templates_published"] = state.get("templates_published", 0) + 1
        revenue_estimate += category["price"]
        published_count += 1

    # Step7: メトリクス記録
    state = record_performance(state, {
        "published_this_run": published_count,
        "templates_total": state.get("templates_published", 0),
        "revenue_estimate_jpy": revenue_estimate,
        "products_on_store": len(state.get("products", [])),
    })

    # Step8: 5テンプレート以上でGemini最適化
    if state.get("templates_published", 0) >= 5:
        print("\n  [最適化] Gemini分析中...")
        opt = optimize("digital_templates", state)
        state = apply_optimization(state, opt)
        print(f"  洞察: {opt['insight']}")
        print(f"  次のアクション: {opt['action']}")

    save_state(STATE_PATH, state)
    print(f"\n[完了] {published_count}件生成 | 通算{state.get('templates_published', 0)}件")


if __name__ == "__main__":
    main()
