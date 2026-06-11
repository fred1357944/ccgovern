"""開發者報告與彙總視圖模型。"""

from __future__ import annotations

from dataclasses import dataclass, field

from ccgovern.models.usage import DailyUsage


@dataclass
class DeveloperReport:
    """可上傳的成品，每位開發者每次收集產一份。"""

    developer_id: str               # email 或 git user.email，穩定鍵
    machine: str = ""
    schema_version: int = 1
    generated_at: str = ""          # ISO8601
    date_start: str = ""
    date_end: str = ""
    daily: list[DailyUsage] = field(default_factory=list)
    total_cost_usd: float = 0.0
    settings_snapshot: dict = field(default_factory=dict)  # {models, mcpServers, plugins}

    def to_dict(self) -> dict:
        return {
            "developer_id": self.developer_id,
            "machine": self.machine,
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "daily": [du.to_dict() for du in self.daily],
            "total_cost_usd": self.total_cost_usd,
            "settings_snapshot": self.settings_snapshot,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "DeveloperReport":
        daily = [DailyUsage.from_dict(x) for x in d.get("daily", [])]
        return cls(
            developer_id=d.get("developer_id", ""),
            machine=d.get("machine", ""),
            schema_version=d.get("schema_version", 1),
            generated_at=d.get("generated_at", ""),
            date_start=d.get("date_start", ""),
            date_end=d.get("date_end", ""),
            daily=daily,
            total_cost_usd=d.get("total_cost_usd", 0.0),
            settings_snapshot=d.get("settings_snapshot", {}),
        )


@dataclass
class DeveloperSummary:
    """團隊表格用的衍生視圖（由 aggregate 計算）。"""

    developer_id: str
    machine: str
    total_cost_usd: float
    month_cost_usd: float
    top_model: str
    last_active: str
