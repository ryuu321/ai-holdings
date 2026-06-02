"""全103製品のemail_templateをヒアリング型（discovery）に一括更新する"""
import json
import pathlib

CONFIG_DIR = pathlib.Path(__file__).parent.parent / "config"

NEW_SUBJECT = "貴社の業務について少しお聞きしてもよいでしょうか"
NEW_TEMPLATE_FILE = "discovery_sequence_1.txt"
NEW_FALLBACK = "日頃より業務にご尽力されていることと存じます。"
NEW_PERSONALIZE_PROMPT = (
    "「{company_name}」のご担当者に向けた、"
    "日常業務の中で発生する繰り返し作業・文書作成の苦労への共感の一文を書いてください。"
    "「御社では〜」で始め、1文以内で。製品名や宣伝は一切含めないこと。"
)

updated = 0
skipped = 0

for cfg_path in sorted(CONFIG_DIR.glob("*.json")):
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[SKIP] {cfg_path.name}: {e}")
        skipped += 1
        continue

    if "email_template" not in data:
        print(f"[SKIP] {cfg_path.name}: email_template なし")
        skipped += 1
        continue

    data["email_template"]["template_file"] = NEW_TEMPLATE_FILE
    data["email_template"]["subject"] = NEW_SUBJECT
    data["email_template"]["fallback_opening"] = NEW_FALLBACK
    data["email_template"]["personalize_prompt"] = NEW_PERSONALIZE_PROMPT

    cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {cfg_path.name}")
    updated += 1

print(f"\n完了: {updated}件更新 / {skipped}件スキップ")
