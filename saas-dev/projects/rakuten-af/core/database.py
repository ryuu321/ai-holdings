"""SQLiteデータベース管理"""
import sqlite3
from pathlib import Path
from config.settings import settings


class Database:
    def __init__(self):
        Path(settings.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id TEXT,
                title TEXT NOT NULL,
                niche TEXT,
                keyword TEXT,
                post_url TEXT,
                template TEXT DEFAULT 'ranking',
                strategy TEXT DEFAULT 'A',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'published'
            );
            CREATE TABLE IF NOT EXISTS errors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS prompt_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL,
                template TEXT NOT NULL,
                prompt_addition TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        self.conn.commit()

    def _migrate(self):
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(articles)").fetchall()]
        if "template" not in cols:
            self.conn.execute("ALTER TABLE articles ADD COLUMN template TEXT DEFAULT 'ranking'")
            self.conn.commit()
        if "strategy" not in cols:
            self.conn.execute("ALTER TABLE articles ADD COLUMN strategy TEXT DEFAULT 'A'")
            self.conn.commit()
        if "account_id" not in cols:
            self.conn.execute("ALTER TABLE articles ADD COLUMN account_id TEXT DEFAULT ''")
            self.conn.commit()

    def record_article(self, post_id: str, title: str, niche: str, keyword: str,
                       post_url: str = "", template: str = "ranking", strategy: str = "A",
                       account_id: str = ""):
        self.conn.execute(
            "INSERT INTO articles (post_id, title, niche, keyword, post_url, template, strategy, account_id) VALUES (?,?,?,?,?,?,?,?)",
            (post_id, title, niche, keyword, post_url, template, strategy, account_id)
        )
        self.conn.commit()

    def record_error(self, job_name: str, error_message: str):
        self.conn.execute(
            "INSERT INTO errors (job_name, error_message) VALUES (?,?)",
            (job_name, error_message)
        )
        self.conn.commit()

    def already_posted(self, keyword: str, cooldown_days: int = 7) -> bool:
        row = self.conn.execute(
            f"SELECT id FROM articles WHERE keyword=? AND created_at >= date('now','-{cooldown_days} days')",
            (keyword,)
        ).fetchone()
        return row is not None

    def get_weekly_summary(self) -> dict:
        row = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM articles
            WHERE created_at >= datetime('now','-7 days')
        """).fetchone()
        return {"article_count": row["cnt"]}

    def get_template_stats(self) -> list[dict]:
        rows = self.conn.execute("""
            SELECT template, COUNT(*) as count
            FROM articles
            WHERE created_at >= date('now','-30 days')
            GROUP BY template
        """).fetchall()
        return [dict(r) for r in rows]

    def get_recent_articles(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute("""
            SELECT title, niche, template, strategy, post_url, created_at
            FROM articles ORDER BY created_at DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_ab_stats(self, days: int = 14) -> dict:
        """A/Bテストの投稿数を比較"""
        rows = self.conn.execute(f"""
            SELECT strategy, COUNT(*) as count
            FROM articles
            WHERE created_at >= date('now','-{days} days')
            GROUP BY strategy
        """).fetchall()
        result = {"A": 0, "B": 0}
        for r in rows:
            if r["strategy"] in result:
                result[r["strategy"]] = r["count"]
        return result

    def save_prompt_improvement(self, version: int, template: str, prompt_addition: str):
        self.conn.execute(
            "INSERT INTO prompt_history (version, template, prompt_addition) VALUES (?,?,?)",
            (version, template, prompt_addition)
        )
        self.conn.commit()

    def get_latest_prompt_improvement(self, template: str) -> str:
        row = self.conn.execute("""
            SELECT prompt_addition FROM prompt_history
            WHERE template=? ORDER BY version DESC LIMIT 1
        """, (template,)).fetchone()
        return row["prompt_addition"] if row else ""
