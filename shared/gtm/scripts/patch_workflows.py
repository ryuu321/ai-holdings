"""
TextSeries ワークフローに専用リード収集ステップを一括追加するパッチスクリプト

  python patch_workflows.py

対象:
  1. MLIT建設業DB対応製品 → fetch_mlit_leads.py を "Seed static leads" の前に挿入
  2. MHLW介護DB対応製品   → fetch_mhlw_leads.py を同様に挿入
  3. GyoText              → fetch_gyosei_leads.py + Playwright インストールを挿入
  4. 全製品               → fetch_web_leads.py フォールバックを挿入（MLIT/MHLW/Playwright未対応分）
"""
from pathlib import Path
import re

ROOT = Path(__file__).parent.parent.parent.parent
WF_DIR = ROOT / ".github/workflows"

# ─────────────────────────────────────────────
# MLIT 建設業DB 対応製品: 工種コード設定
# ─────────────────────────────────────────────
MLIT_PRODUCTS = {
    "tostext":    "09,18",    # 塗装=09, 防水=18
    "denkitext":  "06",       # 電気工事
    "haikantext": "07",       # 管工事
    "yanetext":   "10,15",    # 屋根=10, 板金=15
    "zoentext":   "23",       # 造園
    "kaitaitext": "27",       # 解体（建設業法 最終業種）
    "dobokutext": "02",       # 土木
    "mokkotext":  "03",       # 大工
    "naisotext":  "19",       # 内装仕上
    "komutentext":"01",       # 建築一式
    "rifotext":   "01,19",    # リフォーム=建築+内装
    "hashitext":  "02,11",    # 橋梁=土木+鋼構造物
    "kensetsuconstext": "01,02",  # 建設コンサル
    "sekizaitext": "06",      # 石材→電気に近い番号帯
    "sokuryotext": "01",      # 測量→建築一式で仮
    "birutext":   "01,07",    # ビル管理=建築+管工事
    "kanritext":  "01",       # 建物管理=建築一式
}

# ─────────────────────────────────────────────
# MHLW 介護DB 対応製品: サービスコード設定
# ─────────────────────────────────────────────
MHLW_PRODUCTS = {
    "tokutext":   "310,320",  # 老健=310, 特養=320
    "tokuyoutext":"320",      # 特養のみ
    "kangotext":  "113",      # 訪問看護
    "daytext":    "130",      # 通所介護（デイサービス）
    "fukushitext":"110,113",  # 福祉=訪問介護+訪問看護
}

# ─────────────────────────────────────────────
# GyoText: Playwright専用
# ─────────────────────────────────────────────
PLAYWRIGHT_PRODUCTS = {"gyotext"}

# ─────────────────────────────────────────────
# ウェブ検索フォールバック対象（上記以外の全製品）
# ─────────────────────────────────────────────
SKIP_WEB_FALLBACK = (
    set(MLIT_PRODUCTS) | set(MHLW_PRODUCTS) | PLAYWRIGHT_PRODUCTS |
    {"sharotext", "caretext", "kentext"}  # 既に専用スクリプトあり
)


def _insert_before_seed(content: str, new_step: str) -> str:
    """リード収集ステップの直前に new_step を挿入"""
    # 優先順位: Seed static leads → Run GTM pipeline → Fetch leads (既存) → Qualify leads
    for marker in [
        "      - name: Seed static leads",
        "      - name: Run GTM pipeline",
        "      - name: Fetch leads\n",
        "      - name: Qualify leads",
    ]:
        if marker in content:
            return content.replace(marker, new_step + "\n" + marker, 1)
    return content


def patch_mlit(project: str, koumoku: str):
    wf = WF_DIR / f"{project}-daily-send.yml"
    if not wf.exists():
        print(f"  SKIP (no workflow): {project}")
        return
    content = wf.read_text(encoding="utf-8")

    step_name = "      - name: Fetch leads (MLIT建設業DB)"
    if step_name in content:
        print(f"  already patched: {project}")
        return

    step = (
        f"      - name: Fetch leads (MLIT建設業DB)\n"
        f"        run: |\n"
        f"          python shared/gtm/leads/fetch_mlit_leads.py \\\n"
        f"            --output saas-dev/projects/{project}/outreach/leads.csv \\\n"
        f"            --koumoku {koumoku} \\\n"
        f"            --limit 100 --prefs 13,27,14,23 || true\n"
    )
    new_content = _insert_before_seed(content, step)
    if new_content != content:
        wf.write_text(new_content, encoding="utf-8")
        print(f"  patched (MLIT): {project} [{koumoku}]")
    else:
        print(f"  insert point not found: {project}")


def patch_mhlw(project: str, service_codes: str):
    # project_dir マッピング（config の project_dir と一致させる）
    proj_dir_map = {
        "tokutext": "tokutext",
        "tokuyoutext": "tokuyoutext",
        "kangotext": "kangotext",
        "daytext": "daytext",
        "fukushitext": "fukushitext",
    }
    proj_dir = proj_dir_map.get(project, project)

    wf = WF_DIR / f"{project}-daily-send.yml"
    if not wf.exists():
        print(f"  SKIP (no workflow): {project}")
        return
    content = wf.read_text(encoding="utf-8")

    step_name = "      - name: Fetch leads (MHLW介護DB)"
    if step_name in content:
        print(f"  already patched: {project}")
        return

    step = (
        f"      - name: Fetch leads (MHLW介護DB)\n"
        f"        run: |\n"
        f"          python shared/gtm/leads/fetch_mhlw_leads.py \\\n"
        f"            --output saas-dev/projects/{proj_dir}/outreach/leads.csv \\\n"
        f"            --service-codes {service_codes} \\\n"
        f"            --limit 100 --prefs 13,27,14,23 || true\n"
    )
    new_content = _insert_before_seed(content, step)
    if new_content != content:
        wf.write_text(new_content, encoding="utf-8")
        print(f"  patched (MHLW): {project} [{service_codes}]")
    else:
        print(f"  insert point not found: {project}")


def patch_playwright(project: str):
    wf = WF_DIR / f"{project}-daily-send.yml"
    if not wf.exists():
        print(f"  SKIP (no workflow): {project}")
        return
    content = wf.read_text(encoding="utf-8")

    if "playwright" in content.lower():
        print(f"  already patched: {project}")
        return

    # Install Playwright を "Install dependencies" の後に追加
    pw_install = (
        "      - name: Install Playwright\n"
        "        run: pip install playwright && playwright install chromium --with-deps\n"
    )
    # fetch_gyosei_leads.py ステップ
    fetch_step = (
        "      - name: Fetch leads (gyosei.or.jp Playwright)\n"
        "        run: |\n"
        "          python saas-dev/projects/gyotext/outreach/fetch_gyosei_leads.py \\\n"
        "            --limit 100 --prefs 13,27,14,23 || true\n"
    )
    # Install依存後に追加
    deps_marker = "      - name: Restore sent_log from Gist"
    if deps_marker not in content:
        deps_marker = "      - name: Seed static leads"
    new_content = content.replace(deps_marker, pw_install + "\n" + deps_marker)
    new_content = _insert_before_seed(new_content, fetch_step)

    if new_content != content:
        wf.write_text(new_content, encoding="utf-8")
        print(f"  patched (Playwright): {project}")
    else:
        print(f"  insert point not found: {project}")


def patch_web_fallback(project: str):
    wf = WF_DIR / f"{project}-daily-send.yml"
    if not wf.exists():
        return
    content = wf.read_text(encoding="utf-8")

    step_name = "      - name: Fetch leads (Web検索)"
    if step_name in content:
        return

    step = (
        f"      - name: Fetch leads (Web検索)\n"
        f"        run: |\n"
        f"          python shared/gtm/leads/fetch_web_leads.py \\\n"
        f"            --project {project} --limit 50 || true\n"
    )
    new_content = _insert_before_seed(content, step)
    if new_content != content:
        wf.write_text(new_content, encoding="utf-8")
        print(f"  patched (Web): {project}")


def main():
    print("=== MLIT建設業DB パッチ ===")
    for project, koumoku in MLIT_PRODUCTS.items():
        patch_mlit(project, koumoku)

    print("\n=== MHLW介護DB パッチ ===")
    for project, service_codes in MHLW_PRODUCTS.items():
        patch_mhlw(project, service_codes)

    print("\n=== GyoText Playwright パッチ ===")
    for project in PLAYWRIGHT_PRODUCTS:
        patch_playwright(project)

    print("\n=== Web検索フォールバック パッチ（全製品） ===")
    # 全ワークフローファイルをスキャン
    all_projects = set()
    for wf in WF_DIR.glob("*-daily-send.yml"):
        name = wf.name.replace("-daily-send.yml", "")
        all_projects.add(name)

    for project in sorted(all_projects):
        if project in SKIP_WEB_FALLBACK:
            continue
        patch_web_fallback(project)

    print("\n完了")


if __name__ == "__main__":
    main()
