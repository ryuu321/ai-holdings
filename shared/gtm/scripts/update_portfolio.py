"""
update_portfolio.py  --  TextSeries製品をryuu321.github.ioに自動反映

使い方:
  python update_portfolio.py                     # registry.jsonを読んでサイト更新
  python update_portfolio.py --add tokutext --emoji 🏥 --industry 特養施設 --docs "計画書・報告書"
                                                 # 製品を追加してから更新
  python update_portfolio.py --mark-live tokutext # 既存エントリをliveに変えてから更新
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT   = Path(__file__).resolve().parents[3]          # ai-holdings/
PORTFOLIO   = REPO_ROOT / "shared" / "portfolio" / "registry.json"
GTM_CONFIG  = REPO_ROOT / "shared" / "gtm" / "config"
SITE_REPO   = Path.home() / "ryuu321.github.io"
SITE_INDEX  = SITE_REPO / "index.html"

GRID_START  = "<!-- PORTFOLIO_GRID_START -->"
GRID_END    = "<!-- PORTFOLIO_GRID_END -->"
COUNT_RE    = re.compile(r"(<!-- PORTFOLIO_COUNT -->)\d+(<!-- /PORTFOLIO_COUNT -->)")
BADGE_RE    = re.compile(r"(TextSeries — )\d+(製品 稼働中)")


def load_registry() -> list[dict]:
    return json.loads(PORTFOLIO.read_text(encoding="utf-8"))


def save_registry(data: list[dict]) -> None:
    PORTFOLIO.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_gtm_config(slug: str) -> dict:
    path = GTM_CONFIG / f"{slug}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_card(entry: dict) -> str:
    slug    = entry["slug"]
    emoji   = entry.get("emoji", "📄")
    name    = entry.get("name") or load_gtm_config(slug).get("product_name", slug.title())
    lp_url  = entry.get("lp_url") or load_gtm_config(slug).get("lp_url", "#")
    industry = entry.get("industry", "")
    docs    = entry.get("docs", "")
    return (
        f'        <a href="{lp_url}" target="_blank"\n'
        f'           class="card-hover bg-slate-900 rounded-xl p-5 border border-slate-800 block group">\n'
        f'          <div class="flex items-start justify-between mb-3">\n'
        f'            <div>\n'
        f'              <span class="text-xl">{emoji}</span>\n'
        f'              <p class="font-bold text-white mt-1">{name}</p>\n'
        f'              <p class="text-slate-500 text-xs">{industry}</p>\n'
        f'            </div>\n'
        f'            <span class="tag bg-emerald-950 text-emerald-400">稼働中</span>\n'
        f'          </div>\n'
        f'          <p class="text-slate-400 text-xs leading-relaxed">{docs}</p>\n'
        f'        </a>'
    )


def update_site(registry: list[dict]) -> None:
    live = [e for e in registry if e.get("status") == "live"]
    count = len(live)

    html = SITE_INDEX.read_text(encoding="utf-8")

    # product grid
    cards = "\n".join(build_card(e) for e in live)
    grid_html = (
        f'{GRID_START}\n'
        f'      <div class="grid md:grid-cols-3 gap-3">\n'
        f'{cards}\n'
        f'      </div>\n'
        f'      {GRID_END}'
    )
    if GRID_START in html:
        html = re.sub(
            re.escape(GRID_START) + r".*?" + re.escape(GRID_END),
            grid_html,
            html,
            flags=re.DOTALL,
        )
    else:
        # fallback: replace the old 稼働中 comment block
        html = re.sub(
            r"<!-- 稼働中 -->.*?</div>\s*</div>\s*</section>",
            f"<!-- 稼働中 -->\n      {grid_html}\n    </div>\n  </section>",
            html,
            flags=re.DOTALL,
        )

    # badge and stat counter
    html = COUNT_RE.sub(lambda m: f"{m.group(1)}{count}{m.group(2)}", html)
    html = BADGE_RE.sub(lambda m: f"{m.group(1)}{count}{m.group(2)}", html)

    SITE_INDEX.write_text(html, encoding="utf-8")
    print(f"✅ index.html 更新 ({count}製品稼働中)")

    # git commit & push
    result = subprocess.run(
        ["git", "add", "index.html"],
        cwd=SITE_REPO, capture_output=True
    )
    result = subprocess.run(
        ["git", "commit", "-m", f"portfolio: TextSeries {count}製品稼働中に更新"],
        cwd=SITE_REPO, capture_output=True, text=True
    )
    if "nothing to commit" in result.stdout + result.stderr:
        print("ℹ️  変更なし（pushスキップ）")
        return
    subprocess.run(["git", "push", "origin", "master"], cwd=SITE_REPO)
    print("🚀 ryuu321.github.io にpush完了")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--add",        metavar="SLUG",  help="新製品を追加してliveに設定")
    ap.add_argument("--emoji",      default="📄",     help="絵文字 (--addと一緒に)")
    ap.add_argument("--industry",   default="",       help="業種表示 (--addと一緒に)")
    ap.add_argument("--docs",       default="",       help="書類説明 (--addと一緒に)")
    ap.add_argument("--mark-live",  metavar="SLUG",  help="既存エントリをliveに変更")
    args = ap.parse_args()

    registry = load_registry()

    if args.add:
        slug = args.add
        if any(e["slug"] == slug for e in registry):
            print(f"⚠️  {slug} は既にregistry.jsonにあります。--mark-live を使ってください")
        else:
            cfg = load_gtm_config(slug)
            registry.append({
                "slug":     slug,
                "emoji":    args.emoji,
                "industry": args.industry or cfg.get("icp", {}).get("target_description", "").split("・")[0],
                "docs":     args.docs or "・".join(cfg.get("icp", {}).get("document_types", [])[:3]),
                "status":   "live",
            })
            save_registry(registry)
            print(f"✅ registry.jsonに {slug} を追加")

    if args.mark_live:
        slug = args.mark_live
        found = False
        for e in registry:
            if e["slug"] == slug:
                e["status"] = "live"
                found = True
                break
        if found:
            save_registry(registry)
            print(f"✅ {slug} をliveに変更")
        else:
            print(f"❌ {slug} がregistry.jsonにありません。--add を使ってください")
            sys.exit(1)

    update_site(registry)


if __name__ == "__main__":
    main()
