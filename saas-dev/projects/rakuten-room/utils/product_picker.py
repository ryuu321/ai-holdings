"""products.csv の読み書き"""
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta

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


def get_pending(n: int = 5) -> pd.DataFrame:
    df = _load()
    pending = df[df["posted"] != "True"].copy()
    pending = pending.sort_values("captured_at")
    return pending.head(n)


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
