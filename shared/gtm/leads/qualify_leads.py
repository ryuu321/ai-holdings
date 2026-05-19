"""
ICPスコアリング — リードを自動で3分類する

  python qualify_leads.py --project fudotext --input leads_raw.csv

出力:
  data/{project}/leads_approved.csv  (80点以上 → 送信可)
  data/{project}/leads_review.csv    (60-79点 → 人間レビュー必須)
  data/{project}/leads_rejected.csv  (60点未満 → 自動却下)
"""
import argparse
import csv
import io
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_GTM_DIR = Path(__file__).parent.parent


def load_config(project: str) -> dict:
    path = _GTM_DIR / "config" / f"{project}.json"
    if not path.exists():
        raise FileNotFoundError(f"config/{project}.json が見つかりません。")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def score_lead(company_name: str, email: str, url: str, cfg: dict) -> tuple[int, list[str]]:
    """
    ICP適合度を 0-100点で採点する。
    Returns: (score, reasons)
    """
    icp = cfg["icp"]
    scoring = cfg["scoring"]
    score = 0
    reasons = []

    # ターゲットキーワードチェック（URL + 会社名）
    text = f"{company_name} {url}".lower()
    hit = any(kw in text for kw in icp["target_keywords"])
    if hit:
        score += scoring["target_keyword_hit"]
        reasons.append(f"+{scoring['target_keyword_hit']}: ターゲットキーワード一致")

    # ドメインチェック
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if any(domain.endswith(s) for s in icp["good_domain_suffixes"]):
        score += scoring["good_domain"]
        reasons.append(f"+{scoring['good_domain']}: 法人ドメイン ({domain})")
    elif any(domain.endswith(s) for s in icp["bad_domain_suffixes"]):
        score += scoring["bad_domain_penalty"]
        reasons.append(f"{scoring['bad_domain_penalty']}: 個人/フリーメール ({domain})")

    # 会社種別チェック
    company_types = ["株式会社", "有限会社", "合同会社", "一般社団法人", "公益社団法人"]
    if any(ct in company_name for ct in company_types):
        score += scoring["has_company_type"]
        reasons.append(f"+{scoring['has_company_type']}: 法人登記あり")

    # 除外キーワードチェック（会社名 + URL両方）
    for kw in icp["exclude_keywords"]:
        if kw in company_name or kw in url:
            score += scoring["exclude_keyword_penalty"]
            reasons.append(f"{scoring['exclude_keyword_penalty']}: 除外キーワード「{kw}」")
            break  # 1つ引けば十分

    score = max(0, min(100, score))
    return score, reasons


def qualify(project: str, input_file: str) -> None:
    cfg = load_config(project)
    input_path = Path(input_file)
    if not input_path.is_absolute():
        input_path = _GTM_DIR / "data" / project / input_file

    if not input_path.exists():
        print(f"{input_path} が見つかりません。")
        return

    with open(input_path, encoding="utf-8") as f:
        leads = list(csv.DictReader(f))

    approve_threshold = cfg["scoring"].get("auto_approve_threshold", 80)
    review_threshold = cfg["scoring"].get("review_threshold", 60)
    approved, review, rejected = [], [], []

    for lead in leads:
        company = lead.get("company_name", "")
        email = lead.get("email", "")
        url = lead.get("url", "")
        score, reasons = score_lead(company, email, url, cfg)
        lead["icp_score"] = score
        lead["score_reasons"] = " / ".join(reasons)

        if score >= approve_threshold:
            approved.append(lead)
        elif score >= review_threshold:
            review.append(lead)
        else:
            rejected.append(lead)

    out_dir = _GTM_DIR / "data" / project
    out_dir.mkdir(parents=True, exist_ok=True)

    fields = list(leads[0].keys()) if leads else []

    def write_csv(rows, path):
        with open(path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    write_csv(approved, out_dir / "leads_approved.csv")
    write_csv(review, out_dir / "leads_review.csv")
    write_csv(rejected, out_dir / "leads_rejected.csv")

    print(f"スコアリング完了 ({len(leads)}件)")
    print(f"  承認 (80点+): {len(approved)}件 → leads_approved.csv")
    print(f"  要確認(60-79): {len(review)}件 → leads_review.csv")
    print(f"  却下 (60点未満): {len(rejected)}件 → leads_rejected.csv")

    if review:
        print(f"\n【要確認リスト】 leads_review.csv を目視確認してください:")
        for r in review:
            print(f"  スコア{r['icp_score']}点 | {r['company_name'][:30]} | {r['email']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, help="プロジェクト名（config/{name}.json）")
    parser.add_argument("--input", default="leads_raw.csv", help="入力CSVファイル名")
    args = parser.parse_args()
    qualify(args.project, args.input)
