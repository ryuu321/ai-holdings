"""
Gemini で会社ごとにパーソナライズしたメール文を生成
入力: leads.csv
出力: emails_draft.csv (email, subject, body, status=draft)
"""
import csv
import json
import os
import time
import urllib.request
from pathlib import Path

_DIR = Path(__file__).parent
LEADS_FILE = _DIR / "leads.csv"
DRAFT_FILE = _DIR / "emails_draft.csv"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-1.5-flash-latest"
APP_URL = "https://ai-holdings-jarqe7ynu8kkyqsuxdrabs.streamlit.app/"
LP_URL = "https://ryuu321.github.io/ai-holdings/docs/fudotext.html"

BASE_TEMPLATE = """
件名: 【無料】物件説明文をAIで30秒に短縮するツールを作りました

{company_name} 様

突然のご連絡、失礼いたします。
不動産仲介業者向けAIツール「FudoText」を開発・運営しております、ryuuと申します。

{personalized_opening}

■ FudoTextでできること
・SUUMO（400字）・at home（500字）・HOMES（450字）に自動対応
・ターゲット（ファミリー/投資家/単身者）を選ぶだけで訴求内容を自動最適化
・景品表示法に違反する表現を自動チェック
・登録不要・完全無料でお試しいただけます

■ 実際の生成時間
物件情報の入力: 約30秒 → AI生成: 約15秒 → 合計45秒で完成

今なら無料でお試しいただけます。
{app_url}

ご不明な点がございましたら、お気軽にご返信ください。
ご不要の場合は、その旨ご返信いただければ以降はご連絡いたしません。

---
ryuu
FudoText 開発者
メール: ryuumg03@gmail.com
サービス詳細: {lp_url}
"""


def _load_existing_drafts() -> set[str]:
    if not DRAFT_FILE.exists():
        return set()
    with open(DRAFT_FILE, encoding="utf-8") as f:
        return {row["email"] for row in csv.DictReader(f)}


def _personalize(company_name: str, url: str) -> str:
    if not GEMINI_API_KEY:
        return f"貴社のウェブサイトを拝見し、物件説明文の作成にお時間を取られているのではと思い、ご連絡させていただきました。"

    prompt = f"""不動産仲介会社へのコールドメールの書き出し（1〜2文）を書いてください。

会社名: {company_name}
会社URL: {url}

要件:
- 自然で押しつけがましくない
- 「物件説明文の作成に時間がかかっている」という課題に共感する内容
- 会社名を使って具体的に
- 日本語・敬体
- 50字以内"""

    try:
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 128},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"    Gemini失敗: {e}")
        return f"{company_name}様の物件掲載業務において、説明文作成にお時間を取られているのではと思い、ご連絡いたしました。"


def main():
    if not LEADS_FILE.exists():
        print("leads.csv が見つかりません。collect_leads.py を先に実行してください。")
        return

    with open(LEADS_FILE, encoding="utf-8") as f:
        leads = list(csv.DictReader(f))

    existing = _load_existing_drafts()
    new_leads = [l for l in leads if l["email"] not in existing]
    print(f"メール生成対象: {len(new_leads)}件（スキップ: {len(leads) - len(new_leads)}件）")

    write_header = not DRAFT_FILE.exists()
    with open(DRAFT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "email", "subject", "body", "url", "status"])
        if write_header:
            writer.writeheader()

        for i, lead in enumerate(new_leads, 1):
            name = lead.get("company_name", "ご担当者") or "ご担当者"
            email = lead["email"]
            url = lead.get("url", "")

            print(f"  [{i}/{len(new_leads)}] {name[:30]} <{email}>")
            opening = _personalize(name, url)

            body = BASE_TEMPLATE.format(
                company_name=name,
                personalized_opening=opening,
                app_url=APP_URL,
                lp_url=LP_URL,
            ).strip()

            subject = f"【無料】物件説明文をAIで30秒に短縮するツールを作りました"

            writer.writerow({
                "company_name": name,
                "email": email,
                "subject": subject,
                "body": body,
                "url": url,
                "status": "draft",
            })
            f.flush()

            time.sleep(0.5)

    total = sum(1 for _ in open(DRAFT_FILE, encoding="utf-8")) - 1
    print(f"\n完了。emails_draft.csv 合計: {total}件")


if __name__ == "__main__":
    main()
