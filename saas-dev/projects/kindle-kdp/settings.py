"""設定"""
import os
from pathlib import Path


def _load_env():
    env_path = Path(__file__).parent.parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()


class Settings:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    DB_PATH = str(Path(__file__).parent / "data" / "books.json")


settings = Settings()
