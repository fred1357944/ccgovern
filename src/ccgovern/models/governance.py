"""治理模型：預算、政策、違規。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Budget:
    scope: str                      # "team" 或 "dev"
    target: str                     # team 為 ""，dev 為 developer_id
    monthly_cap_usd: float
    alert_threshold: float = 0.8    # 預估達上限 80% 時告警

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Budget":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})


@dataclass
class Policy:
    allowed_models: list[str] = field(default_factory=list)    # 空 = 全允許
    allowed_mcp: list[str] = field(default_factory=list)
    blocked_mcp: list[str] = field(default_factory=list)
    allowed_plugins: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Policy":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})


@dataclass
class Violation:
    developer_id: str
    kind: str                       # "model" | "mcp" | "plugin"
    detail: str
    severity: str = "warning"       # "warning" | "error"

    def to_dict(self) -> dict:
        return asdict(self)
