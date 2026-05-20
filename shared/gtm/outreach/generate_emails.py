"""
承認済みリードからメール草稿を生成する
  python generate_emails.py --project fudotext [--dry-run] [--limit 50]
入力: shared/gtm/data/{project}/leads_approved.csv
出力: saas-dev/projects/fudosan-copy/outreach/emails_draft.csv
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass  # pytest / non-reconfigurable stdout

_GTM_DIR = Path(__file__).parent.parent
_FUDOSAN_DIR = _GTM_DIR.parent.parent / "saas-dev" / "projects" / "fudosan-copy"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=_GTM_DIR.parent.parent / ".env")
except ImportError:
    pass


def load_config(project: str) -> dict:
    path = _GTM_DIR / "config" / f"{project}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_template(name: str) -> str:
    path = _GTM_DIR / "outreach" / "templates" / name
    return path.read_text(encoding="utf-8")


def _gemini_personalize(company_name: str, prompt_template: str, model: str, api_key: str) -> tuple[str, bool]:
    if not api_key:
        return "", False
    prompt = prompt_template.format(company_name=company_name)
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 100, "temperature": 0.7}
    }).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=payload,
                                          headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            return text, True
        except urllib.error.HTTPError as e:
            if e.code == 429:
                sleep = 2 ** (attempt + 1)
                print(f"    Gemini 429 → {sleep}s待機")
                time.sleep(sleep)
            else:
                return "", False
        except Exception:
            return "", False
    return "", False


_COMPANY_KEYWORDS = ["株式会社", "有限会社", "合同会社", "一般社団法人", "公益社団法人"]

# これらが含まれる文字列は会社名ではなくブログタイトル等と判定してスキップ
_BLOG_SIGNALS = [
    "コツ", "方法", "選び方", "探し方", "ランキング", "比較", "一覧",
    "とは", "について", "の仕方", "ガイド", "まとめ", "おすすめ",
    "お問い合わせ方法", "メールで", "相談を", "スムーズ", "名簿", "営業リスト",
]


def _clean_company_name(raw: str) -> str:
    """SEOタイトルから会社名だけを抽出。取れなければ空文字を返す（呼び出し側でスキップ）。"""
    # ブログタイトルシグナルが入っていたら即スキップ
    if any(sig in raw for sig in _BLOG_SIGNALS):
        return ""
    # 【ViVi（ヴィヴィ）不動産】のような【】パターン
    m = re.search(r'[【(]([^)】]{2,30}不動産[^)】]{0,10})[)】]', raw)
    if m:
        return m.group(1).strip()
    # ｜/|/-/—で分割して株式会社等を含む部分を探す
    for sep in ["｜", "|", "–", "-", "—"]:
        if sep not in raw:
            continue
        for part in raw.split(sep):
            part = part.strip()
            if any(kw in part for kw in _COMPANY_KEYWORDS) and len(part) <= 25:
                return part
    # 株式会社/有限会社/合同会社から始まるパターン
    m2 = re.search(r'((?:株式会社|有限会社|合同会社)[^\s　。、！？]{1,15})', raw)
    if m2:
        return m2.group(1).strip()
    # 末尾に株式会社等がつくパターン（東洋不動産株式会社）
    m3 = re.search(r'([^\s　。、！？・]{1,12}(?:株式会社|有限会社|合同会社))', raw)
    if m3:
        return m3.group(1).strip()
    return ""


def load_existing_emails(draft_file: Path, sent_log: Path) -> set[str]:
    emails = set()
    for path in [draft_file, sent_log]:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                emails.update(row["email"] for row in csv.DictReader(f))
    return emails


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="fudotext")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    cfg = load_config(args.project)
    template = load_template("sequence_1.txt")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    sender_address = os.environ.get("SENDER_ADDRESS", "")
    model = cfg.get("gemini_model", "gemini-2.0-flash-lite")
    fallback = cfg["email_template"]["fallback_opening"]
    personalize_prompt = cfg["email_template"]["personalize_prompt"]
    subject = cfg["email_template"]["subject"]

    approved_path = _GTM_DIR / "data" / args.project / "leads_approved.csv"
    if not approved_path.exists():
        print(f"leads_approved.csv が見つかりません: {approved_path}")
        print("先に qualify_leads.py を実行してください。")
        return

    draft_file = _FUDOSAN_DIR / "outreach" / "emails_draft.csv"
    sent_log = _FUDOSAN_DIR / "outreach" / "sent_log.csv"
    existing = load_existing_emails(draft_file, sent_log)

    with open(approved_path, encoding="utf-8") as f:
        leads = list(csv.DictReader(f))

    targets = [l for l in leads if l["email"] not in existing][:args.limit]
    print(f"生成対象: {len(targets)}件 (承認済み{len(leads)}件 / 新規{len(targets)}件)")

    if not targets:
        print("新規リードなし。ends_leads.py で収集してから再実行してください。")
        return

    if args.dry_run:
        for l in targets:
            print(f"  {l['company_name'][:35]} | {l['email']} | score={l.get('icp_score','?')}")
        print(f"\n（--dry-run: {len(targets)}件を生成予定・送信しません）")
        return

    fields = ["company_name", "email", "subject", "body", "url", "status", "personalized"]
    write_header = not draft_file.exists()

    generated = 0
    with open(draft_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            writer.writeheader()

        for i, lead in enumerate(targets, 1):
            raw_name = lead["company_name"]
            company = _clean_company_name(raw_name)
            email = lead["email"]
            url = lead.get("url", "")
            if not company:
                print(f"  [{i}/{len(targets)}] SKIP（会社名不明: {raw_name[:30]}）")
                continue
            print(f"  [{i}/{len(targets)}] {company[:30]} ...", end=" ")

            opening, personalized = _gemini_personalize(company, personalize_prompt, model, api_key)
            if not opening:
                opening = fallback
                personalized = False

            body = template.format(
                company_name=company,
                sender_name=cfg["sender_name"],
                product_name=cfg["product_name"],
                app_url=cfg["app_url"],
                lp_url=cfg["lp_url"],
                sender_email=cfg["sender_email"],
                sender_address=sender_address,
                personalized_opening=opening,
            )

            writer.writerow({
                "company_name": company,
                "email": email,
                "subject": subject,
                "body": body,
                "url": url,
                "status": "draft",
                "personalized": str(personalized),
            })
            f.flush()
            generated += 1
            print(f"{'AI' if personalized else 'FB'}")
            time.sleep(0.5)

    print(f"\n完了。{generated}件を emails_draft.csv に追加しました。")


if __name__ == "__main__":
    main()
