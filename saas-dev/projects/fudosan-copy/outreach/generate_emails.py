"""
Gemini で会社ごとにパーソナライズしたメール文を生成
入力: leads.csv
出力: emails_draft.csv (email, subject, body, status=draft)
"""
import csv
import json
import os
import re
import time
import urllib.request
from pathlib import Path

_DIR = Path(__file__).parent
LEADS_FILE = _DIR / "leads.csv"
DRAFT_FILE = _DIR / "emails_draft.csv"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-2.0-flash-lite"
APP_URL = "https://ai-holdings-jarqe7ynu8kkyqsuxdrabs.streamlit.app/"
LP_URL = "https://ryuu321.github.io/ai-holdings/docs/fudotext.html"

# 正しい日本語ビジネスメール形式
BASE_TEMPLATE = """{company_name}
ご担当者様

突然のご連絡、失礼いたします。
不動産仲介業者向けAIツール「FudoText」を開発しております、真柄龍聖と申します。

{personalized_opening}

■ FudoTextでできること
・SUUMO（400字）・at home（500字）・HOMES（450字）に自動対応
・ターゲット（ファミリー/投資家/単身者）を選ぶだけで訴求内容を自動最適化
・景品表示法に違反する表現を自動チェック
・登録不要・完全無料でお試しいただけます

■ 生成時間の目安
物件情報の入力: 約30秒 → AI生成: 約15秒 → 合計45秒で完成

無料でお試しいただけます:
{app_url}

ご不明な点はお気軽にご返信ください。
ご不要の場合はその旨ご返信いただければ、以降はご連絡いたしません。

━━━━━━━━━━━━━━━━━━
真柄 龍聖
FudoText 開発者
Mail: ryuumg03@gmail.com
Web: {lp_url}
━━━━━━━━━━━━━━━━━━"""


def _extract_company_name(raw: str) -> str:
    """ページタイトルから会社名だけを抽出"""
    # ｜や|で分割して株式会社・有限会社等を含む部分を優先
    parts = re.split(r"[｜|｜]", raw)
    company_keywords = ["株式会社", "有限会社", "合同会社", "一般社団法人",
                        "公益社団法人", "一般財団法人", "不動産", "リアルティ",
                        "ホーム", "ハウス", "コーポレーション"]
    for part in parts:
        part = part.strip()
        if any(kw in part for kw in company_keywords) and len(part) < 30:
            return part
    # 見つからなければ最初のパートを返す
    first = parts[0].strip()
    return first[:25] if first else "ご担当者"


def _load_existing_drafts() -> set[str]:
    if not DRAFT_FILE.exists():
        return set()
    with open(DRAFT_FILE, encoding="utf-8") as f:
        return {row["email"] for row in csv.DictReader(f)}


def _load_sent() -> set[str]:
    sent_log = _DIR / "sent_log.csv"
    if not sent_log.exists():
        return set()
    with open(sent_log, encoding="utf-8") as f:
        return {row["email"] for row in csv.DictReader(f)}


def _personalize(company_name: str, url: str) -> str:
    fallback = f"貴社の物件説明文作成業務において、ご担当者様のお時間を少しでも省けるのではと思い、ご連絡させていただきました。"

    if not GEMINI_API_KEY:
        return fallback

    prompt = f"""不動産仲介会社へのビジネスメールの書き出し（1〜2文、60字以内）を書いてください。

会社名: {company_name}

要件:
- 自然で押しつけがましくない
- 物件説明文の作成工数を削減できるかもしれないという文脈で
- 敬体・丁寧語
- 会社名は使わなくてよい
- 60字以内で完結させること"""

    try:
        payload = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 100},
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GEMINI_API_KEY}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return text if text else fallback
    except Exception as e:
        print(f"    Gemini失敗: {e}")
        return fallback


def main():
    if not LEADS_FILE.exists():
        print("leads.csv が見つかりません。")
        return

    with open(LEADS_FILE, encoding="utf-8") as f:
        leads = list(csv.DictReader(f))

    existing = _load_existing_drafts()
    sent = _load_sent()
    skip = existing | sent
    new_leads = [l for l in leads if l["email"] not in skip]
    print(f"生成対象: {len(new_leads)}件（スキップ: {len(leads) - len(new_leads)}件）")

    write_header = not DRAFT_FILE.exists()
    with open(DRAFT_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "email", "subject", "body", "url", "status"])
        if write_header:
            writer.writeheader()

        for i, lead in enumerate(new_leads, 1):
            raw_name = lead.get("company_name", "") or ""
            company = _extract_company_name(raw_name)
            email = lead["email"]
            url = lead.get("url", "")

            print(f"  [{i}/{len(new_leads)}] {company} <{email}>")
            opening = _personalize(company, url)

            body = BASE_TEMPLATE.format(
                company_name=company,
                personalized_opening=opening,
                app_url=APP_URL,
                lp_url=LP_URL,
            )

            writer.writerow({
                "company_name": company,
                "email": email,
                "subject": "【無料ツール】物件説明文の作成時間を大幅に短縮できます",
                "body": body,
                "url": url,
                "status": "draft",
            })
            f.flush()
            time.sleep(4)

    total = sum(1 for _ in open(DRAFT_FILE, encoding="utf-8")) - 1
    print(f"\n完了。emails_draft.csv: {total}件")


if __name__ == "__main__":
    main()
