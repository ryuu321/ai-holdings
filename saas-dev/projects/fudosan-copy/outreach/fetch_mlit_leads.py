"""
国土交通省 宅建業者名簿から不動産会社URLを収集
公開データ: https://www.mlit.go.jp/totikensangyo/const/1_6_bt_000083.html
Excel形式で都道府県ごとに公開されている

このスクリプトは:
1. 国交省の宅建業者名簿ページをフェッチ
2. 各都道府県のExcelリンクを取得
3. Excelをダウンロードして会社名・電話番号を抽出
4. 会社名でGoogle検索 → URLを取得（手動補完が必要な場合あり）
5. urls.txt に書き出す

注意: Excelには電話番号はあるがメアド・URLは含まれない
→ collect_leads.py が各URLからメアドを収集する
"""
import re
import time
import urllib.request
from pathlib import Path

_DIR = Path(__file__).parent
URLS_FILE = _DIR / "urls.txt"

MLIT_BASE = "https://www.mlit.go.jp"
MLIT_PAGE = f"{MLIT_BASE}/totikensangyo/const/1_6_bt_000083.html"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; FudoTextResearch/1.0)"}


def _fetch(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            enc = r.headers.get_content_charset("utf-8")
            return raw.decode(enc, errors="ignore")
    except Exception as e:
        print(f"  取得失敗: {url} — {e}")
        return ""


def main():
    print("国交省 宅建業者名簿ページにアクセス中...")
    html = _fetch(MLIT_PAGE)
    if not html:
        print("ページ取得失敗")
        return

    # Excelリンクを抽出
    excel_links = re.findall(r'href="([^"]+\.xlsx?)"', html, re.IGNORECASE)
    excel_links = [l if l.startswith("http") else MLIT_BASE + l for l in excel_links]
    print(f"Excelファイル: {len(excel_links)}件")

    # 既存URLを読み込み
    existing = set()
    if URLS_FILE.exists():
        existing = {u.strip() for u in URLS_FILE.read_text(encoding="utf-8").splitlines()
                   if u.strip() and not u.startswith("#")}

    print(f"\n既存URL: {len(existing)}件")
    print(f"""
このスクリプトはExcelダウンロードまで対応しています。
メアド収集には以下のワークフローを使ってください:

1. 宅建業者名簿Excel を手動DL（または自動処理が必要なら openpyxl を pip install）
2. 会社名でGoogle検索 → 公式サイトURLを urls.txt に追加
3. python collect_leads.py でメアドを一括収集

または、以下のような不動産会社ディレクトリからURLを直接収集:
- https://www.homes.co.jp/company/      (HOMES 業者一覧)
- https://www.athome.co.jp/company/     (at home 業者一覧)
- https://suumo.jp/edit/kyoten/         (SUUMO 業者検索)

これらのページから会社URLをスクレイピングすると効率的です。
""")

    # HOMES業者一覧から直接収集する簡易版
    print("HOMES業者一覧から収集を試みます...")
    collected = set()
    for page in range(1, 6):  # 最初の5ページ
        url = f"https://www.homes.co.jp/company/list/?page={page}"
        html = _fetch(url)
        if not html:
            break
        # 業者の公式サイトURLを探す（HOMESの業者ページURLを収集）
        company_urls = re.findall(r'href="(https://www\.homes\.co\.jp/company/[^"]+/)"', html)
        for cu in company_urls:
            if cu not in existing and cu not in collected:
                collected.add(cu)
        print(f"  ページ {page}: {len(company_urls)}件")
        time.sleep(1)

    if collected:
        with open(URLS_FILE, "a", encoding="utf-8") as f:
            for u in sorted(collected):
                f.write(u + "\n")
        print(f"\nurls.txt に {len(collected)}件追加しました")
    else:
        print("URLを取得できませんでした。手動でurls.txtにURLを追加してください。")


if __name__ == "__main__":
    main()
