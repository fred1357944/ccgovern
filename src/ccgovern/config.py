"""路徑、常數與使用者設定。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()

CONFIG_DIR = HOME / ".config" / "ccgovern"
DB_FILE = CONFIG_DIR / "ccgovern.db"
INGEST_DIR = CONFIG_DIR / "ingest"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

# 每位開發者本機的 Claude Code 資料來源
CC_PROJECTS_DIR = HOME / ".claude" / "projects"
CC_STATS_CACHE = HOME / ".claude" / "stats-cache.json"
CC_SETTINGS_FILE = HOME / ".claude" / "settings.json"


@dataclass
class Settings:
    """CCGovern 使用者設定，存於 ~/.config/ccgovern/settings.json。"""

    ingest_dir: str = str(INGEST_DIR)
    default_monthly_budget_usd: float = 200.0

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                return cls(**{k: v for k, v in data.items() if k in cls.__annotations__})
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(self.__dict__, ensure_ascii=False, indent=2), encoding="utf-8"
        )
