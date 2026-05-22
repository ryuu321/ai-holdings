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
_SAAS_PROJECTS_DIR = _GTM_DIR.parent.parent / "saas-dev" / "projects"
_FUDOSAN_DIR = _SAAS_PROJECTS_DIR / "fudosan-copy"

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


_COMPANY_KEYWORDS = ["株式会社", "有限会社", "合同会社", "一般社団法人", "公益社団法人",
                     "社会保険労務士法人", "社労士法人", "社会保険労務士事務所", "社労士事務所",
                     "行政書士法人", "司法書士法人", "税理士法人"]

# これらが含まれる文字列は会社名ではなくブログタイトル等と判定してスキップ
_BLOG_SIGNALS = [
    "コツ", "方法", "選び方", "探し方", "ランキング", "比較", "一覧",
    "とは", "について", "の仕方", "ガイド", "まとめ", "おすすめ",
    "お問い合わせ方法", "メールで", "相談を", "スムーズ", "名簿", "営業リスト",
    "お任せ", "ご相談", "はこちら", "サポート", "にお任せ",
]


def _clean_company_name(raw: str, hint_keywords: list[str] | None = None) -> str:
    """SEOタイトルから会社名だけを抽出。取れなければ空文字を返す（呼び出し側でスキップ）。
    hint_keywords: config の icp.company_name_hint_keywords（業種固有キーワード）

    ロジック順序:
    0. 前置マーケティング語を除去（「全国対応の〇〇事務所」→「〇〇事務所」）
    1. 区切り文字で分割 → 会社名が取れたらブログシグナルに関係なく返す
       （「お任せ | 株式会社〇〇」の左側シグナルで正当企業を弾かないため）
    2. 【】パターン
    3. ブログシグナルで弾く（区切りなし限定）
    4. 法人格前置パターン（「〜と言えば、株式会社XXX」等）
    5. 末尾法人格パターン
    6. hint_keyword を含む短い名前を信頼（fetch_leads で既にAI検証済み）
    """
    _LEAD_TYPES = "株式会社|有限会社|合同会社|社会保険労務士法人|社労士法人|行政書士法人|司法書士法人|税理士法人"
    _TRAIL_TYPES = "株式会社|有限会社|合同会社|社会保険労務士法人|社労士法人|社会保険労務士事務所|社労士事務所|工務店"

    # Step0: 前置マーケティング語除去 ＋ 「法人　固有名詞」の全角スペースを結合
    raw = re.sub(r'^(?:全国対応の?|全国の|地域密着型?の?)[　\s]*', '', raw)
    raw = re.sub(r'(社会保険労務士法人|社労士法人|株式会社|有限会社|合同会社|行政書士法人|司法書士法人|税理士法人)　(.{1,15})$', r'\1\2', raw)

    # Step1: 区切り文字で分割（ブログシグナルチェックより先）
    for sep in ["｜", "|", "–", "—", " - "]:
        if sep not in raw:
            continue
        for part in raw.split(sep):
            part = part.strip()
            if any(kw in part for kw in _COMPANY_KEYWORDS) and len(part) <= 30:
                return part
            if hint_keywords and any(kw in part for kw in hint_keywords) and len(part) <= 25:
                return part

    # Step2: 【】パターン
    for m in re.finditer(r'[【(]([^)】]{2,30})[)】]', raw):
        candidate = m.group(1).strip()
        if any(kw in candidate for kw in _COMPANY_KEYWORDS):
            return candidate
        if hint_keywords and any(kw in candidate for kw in hint_keywords) and len(candidate) <= 25:
            return candidate

    # Step3: 区切りなしの場合のみブログシグナルで弾く
    if any(sig in raw for sig in _BLOG_SIGNALS):
        return ""

    # Step4: 法人格前置パターン（「〜と言えば、株式会社XXX」等）
    m2 = re.search(rf'((?:{_LEAD_TYPES})[^\s　。、！？]{{1,20}})', raw)
    if m2:
        return m2.group(1).strip()

    # Step5: 末尾法人格パターン（「XXX工務店」等）
    m3 = re.search(rf'([^\s　。、！？・「」【】]{{1,20}}(?:{_TRAIL_TYPES}))$', raw.strip())
    if m3:
        return m3.group(1).strip()

    # Step6: hint_keyword を含む短い名前を信頼（スペースなし＝事務所名、fetch_leads.py でAI検証済み）
    if hint_keywords and any(kw in raw for kw in hint_keywords) and len(raw) <= 20 and " " not in raw and "　" not in raw:
        return raw

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
    template_file = cfg.get("email_template", {}).get("template_file", "sequence_1.txt")
    template = load_template(template_file)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    sender_address = os.environ.get("SENDER_ADDRESS", "")
    model = cfg.get("gemini_model", "gemini-3.1-flash-lite")
    fallback = cfg["email_template"]["fallback_opening"]
    personalize_prompt = cfg["email_template"]["personalize_prompt"]
    subject = cfg["email_template"]["subject"]

    approved_path = _GTM_DIR / "data" / args.project / "leads_approved.csv"
    if not approved_path.exists():
        print(f"leads_approved.csv が見つかりません: {approved_path}")
        print("先に qualify_leads.py を実行してください。")
        return

    project_dir_name = cfg.get("project_dir", "fudosan-copy")
    _project_dir = _SAAS_PROJECTS_DIR / project_dir_name
    draft_file = _project_dir / "outreach" / "emails_draft.csv"
    sent_log = _project_dir / "outreach" / "sent_log.csv"
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

    hint_keywords = cfg.get("icp", {}).get("company_name_hint_keywords", [])
    generated = 0
    with open(draft_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            writer.writeheader()

        for i, lead in enumerate(targets, 1):
            raw_name = lead["company_name"]
            company = _clean_company_name(raw_name, hint_keywords)
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
