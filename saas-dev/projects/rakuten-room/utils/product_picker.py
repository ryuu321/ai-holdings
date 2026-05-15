"""products.csv の読み書き"""
import re
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, unquote

CSV_PATH = Path(__file__).parent.parent / "data" / "products.csv"
COLUMNS = [
    "url", "name", "category", "buyer_persona", "price", "rating", "review_count", "score",
    "copy_short_polite", "copy_short_casual", "copy_short_mom",
    "copy_medium_polite", "copy_medium_casual", "copy_medium_mom",
    "copy_long_polite", "copy_long_casual", "copy_long_mom",
    "hashtags", "evidence_url", "captured_at",
    "posted", "posted_at", "tone_used",
]
JST = timezone(timedelta(hours=9))


def _load() -> pd.DataFrame:
    if CSV_PATH.exists() and CSV_PATH.stat().st_size > 0:
        return pd.read_csv(CSV_PATH, dtype=str).fillna("")
    return pd.DataFrame(columns=COLUMNS)


def _save(df: pd.DataFrame):
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_PATH, index=False)


def load_products() -> pd.DataFrame:
    return _load()


def _extract_shop(url: str) -> str:
    url = str(url)
    if "hb.afl.rakuten" in url:
        qs = parse_qs(urlparse(url).query)
        actual = qs.get("pc", [""])[0]
        if actual:
            url = unquote(actual)
    m = re.search(r"item\.rakuten\.co\.jp/([^/]+)/", url)
    return m.group(1) if m else ""


def get_pending(n: int = 5, min_score: float = 0.0) -> pd.DataFrame:
    df = _load()
    pending = df[df["posted"] != "True"].copy()
    pending["_score"] = pd.to_numeric(pending.get("score", 0), errors="coerce").fillna(0)

    if min_score > 0:
        room_items = pending[pending["_score"] >= min_score]
        # ROOM確認済みが十分あればそれだけ返す、なければ全体から返す
        if len(room_items) >= min(n, 5):
            pending = room_items

    # score降順（ROOM直接スクレイプ品=9.99が最優先）、同スコアはcaptured_at昇順
    pending = pending.sort_values(["_score", "captured_at"], ascending=[False, True])
    return pending.drop(columns=["_score"]).head(n)


def mark_posted(url: str, tone_used: str):
    df = _load()
    mask = df["url"] == url
    df.loc[mask, "posted"] = "True"
    df.loc[mask, "posted_at"] = datetime.now(JST).strftime("%Y-%m-%d %H:%M")
    df.loc[mask, "tone_used"] = tone_used
    _save(df)


def count_pending() -> int:
    df = _load()
    return int((df["posted"] != "True").sum())


def append_products(new_rows: list[dict]):
    df = _load()
    existing_urls = set(df["url"].tolist())
    filtered = [r for r in new_rows if r.get("url") not in existing_urls]
    if not filtered:
        return
    new_df = pd.DataFrame(filtered, columns=COLUMNS)
    combined = pd.concat([df, new_df], ignore_index=True)
    _save(combined)
    print(f"  {len(filtered)}件追加（重複スキップ: {len(new_rows) - len(filtered)}件）")
