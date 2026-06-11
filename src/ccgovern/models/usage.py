"""用量資料模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class UsageRecord:
    """一筆帶 usage 的 JSONL 記錄。注意：JSONL 本身無模型名。"""

    uuid: str
    timestamp: str            # ISO8601，原樣
    date: str                 # "YYYY-MM-DD"，由 timestamp 推導
    session_id: str = ""
    cwd: str = ""
    git_branch: str = ""
    version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "UsageRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})


@dataclass
class DailyUsage:
    """彙總單位：(開發者, 日期, 模型)。成本為自算，永不從來源讀。"""

    developer_id: str
    date: str                 # YYYY-MM-DD
    model: str                # 完整模型 id，如 claude-opus-4-5-20251101
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DailyUsage":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})
