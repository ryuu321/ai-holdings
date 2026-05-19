"""
コールドメール PDCA スクリプト

sent_log.csv の返信率を分析し、低ければ Gemini でテンプレを改善する。

実行:
  python outreach_pdca.py --sent-log path/to/sent_log.csv --project fudotext
  python outreach_pdca.py --sent-log path/to/sent_log.csv --project fudotext --dry-run
"""
import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

_GTM_DIR = Path(__file__).parent.parent
_TEMPLATES_DIR = _GTM_DIR / "outreach" / "templates"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")

REPLY_RATE_THRESHOLD = 0.02   # 2%未満で改善トリガー
MIN_SENT_FOR_PDCA = 10        # 10件以上送信後にPDCA開始
PDCA_COOLDOWN_DAYS = 14       # 14日以内に改善済みなら再改善しない


def load_sent_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def calc_metrics(log: list[dict]) -> dict:
    sent = [r for r in log if r.get("result") == "sent"]
    replied = [r for r in log if r.get("result") == "replied"]
    followup = [r for r in log if r.get("result") == "followup"]
    followup_failed = [r for r in log if r.get("result") == "followup_failed"]

    total_sent = len(sent) + len(replied) + len(followup) + len(followup_failed)
    total_replied = len(replied)
    reply_rate = total_replied / total_sent if total_sent > 0 else 0.0

    # 直近7日の送信数
    cutoff = datetime.now() - timedelta(days=7)
    recent_sent = sum(
        1 for r in log
        if r.get("sent_at") and _parse_dt(r["sent_at"]) and _parse_dt(r["sent_at"]) >= cutoff
    )

    return {
        "total_sent": total_sent,
        "total_replied": total_replied,
        "total_followup": len(followup),
        "reply_rate": reply_rate,
        "recent_sent_7d": recent_sent,
    }


def _parse_dt(s: str):
    try:
        return datetime.strptime(s[:16], "%Y-%m-%d %H:%M")
    except Exception:
        return None


def _last_pdca_date(seq1: str) -> datetime | None:
    """sequence_1.txt の先頭コメントから最終PDCA日を読む"""
    for line in seq1.splitlines():
        if line.startswith("# PDCA:"):
            try:
                return datetime.strptime(line.split(":", 1)[1].strip(), "%Y-%m-%d")
            except Exception:
                return None
    return None


def _gemini_improve(seq1: str, seq2: str, metrics: dict, project_cfg: dict) -> tuple[str, str, str]:
    """Gemini にテンプレ改善を依頼して (new_seq1, new_seq2, reason) を返す"""
    if not GEMINI_API_KEY:
        return seq1, seq2, "GEMINI_API_KEY未設定"

    prompt = f"""あなたは BtoB コールドメールの専門家です。
以下の不動産仲介会社向けコールドメールキャンペーンの結果を見て、返信率を改善してください。

【現在の成績】
- 送信数: {metrics['total_sent']}件
- 返信数: {metrics['total_replied']}件
- 返信率: {metrics['reply_rate']*100:.1f}%（目標: 2%以上）

【製品情報】
- 製品名: {project_cfg.get('product_name', 'FudoText')}
- URL: {project_cfg.get('app_url', '')}

【現在の1通目テンプレ】
{seq1}

【現在のフォローアップテンプレ】
{seq2}

【改善指示】
1. 件名に相当する冒頭を変える（受信者が開封したくなるよう）
2. 価値提案をより具体的な数字で訴求する
3. CTAを1つに絞り行動を明確にする
4. 全体的に短くする（読む時間: 30秒以内）
5. テンプレート変数（{{company_name}}等）は必ず残す

以下のJSON形式のみで回答してください（他の文章は不要）:
{{"sequence_1": "改善後の1通目全文", "sequence_2": "改善後のフォローアップ全文", "reason": "変更点の要約（日本語1〜2文）"}}
"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={GEMINI_API_KEY}"
    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    try:
        req = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        text = resp["candidates"][0]["content"]["parts"][0]["text"].strip()
        # コードブロックを除去
        if text.startswith("```"):
            text = "\n".join(text.splitlines()[1:])
        if text.endswith("```"):
            text = "\n".join(text.splitlines()[:-1])
        data = json.loads(text)
        return data["sequence_1"], data["sequence_2"], data["reason"]
    except Exception as e:
        return seq1, seq2, f"Gemini呼び出し失敗: {e}"


def _notify_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHANNEL_ID, "text": message}).encode()
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception as e:
        print(f"Telegram通知失敗: {e}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sent-log", required=True)
    parser.add_argument("--project", default="fudotext")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    log = load_sent_log(Path(args.sent_log))
    m = calc_metrics(log)

    print(f"[PDCA] 送信: {m['total_sent']}件 / 返信: {m['total_replied']}件 / "
          f"返信率: {m['reply_rate']*100:.1f}%")

    # プロジェクト設定を読む
    cfg_file = _GTM_DIR / "config" / f"{args.project}.json"
    project_cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}

    seq1_path = _TEMPLATES_DIR / "sequence_1.txt"
    seq2_path = _TEMPLATES_DIR / "sequence_2.txt"
    seq1 = seq1_path.read_text(encoding="utf-8")
    seq2 = seq2_path.read_text(encoding="utf-8")

    # PDCA が必要かチェック
    needs_pdca = (
        m["total_sent"] >= MIN_SENT_FOR_PDCA
        and m["reply_rate"] < REPLY_RATE_THRESHOLD
    )

    # クールダウン確認
    last_pdca = _last_pdca_date(seq1)
    if last_pdca and (datetime.now() - last_pdca).days < PDCA_COOLDOWN_DAYS:
        print(f"[PDCA] クールダウン中（最終改善: {last_pdca.date()}）。スキップ。")
        needs_pdca = False

    reason = "改善不要"
    if needs_pdca:
        print(f"[PDCA] 返信率 {m['reply_rate']*100:.1f}% < {REPLY_RATE_THRESHOLD*100:.0f}% → テンプレ改善開始")
        if not args.dry_run:
            new_seq1, new_seq2, reason = _gemini_improve(seq1, seq2, m, project_cfg)
            today = datetime.now().strftime("%Y-%m-%d")
            # PDCAタグを先頭に付与
            new_seq1 = f"# PDCA: {today}\n{new_seq1}"
            seq1_path.write_text(new_seq1, encoding="utf-8")
            seq2_path.write_text(new_seq2, encoding="utf-8")
            print(f"[PDCA] テンプレ更新完了: {reason}")
        else:
            reason = "[dry-run] 実際には改善しません"
            print(f"[PDCA] dry-run モード: Gemini は呼び出しません")
    else:
        if m["total_sent"] < MIN_SENT_FOR_PDCA:
            print(f"[PDCA] 送信数不足（{m['total_sent']}/{MIN_SENT_FOR_PDCA}件）。次回以降に判断。")
        else:
            print(f"[PDCA] 返信率 {m['reply_rate']*100:.1f}% ≥ {REPLY_RATE_THRESHOLD*100:.0f}% → 改善不要")

    # Telegram サマリー
    status = "🔄 テンプレ改善" if (needs_pdca and not args.dry_run) else "✅ 現状維持"
    msg = (
        f"📊 FudoText 週次PDCAレポート\n"
        f"送信: {m['total_sent']}件 / 返信: {m['total_replied']}件\n"
        f"返信率: {m['reply_rate']*100:.1f}%（目標2%）\n"
        f"直近7日送信: {m['recent_sent_7d']}件\n"
        f"\n{status}: {reason}"
    )
    _notify_telegram(msg)
    print(f"\n[PDCA] Telegram通知送信済み")


if __name__ == "__main__":
    main()
