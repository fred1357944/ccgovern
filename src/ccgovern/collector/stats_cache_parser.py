"""讀取 ~/.claude/stats-cache.json — 模型維度的唯一來源。

注意（已驗證）：dailyActivity / dailyModelTokens 是 LIST 不是 dict；
modelUsage 是 dict（含真實模型名 + 各 tier 拆分，但 all-time 無日期）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ccgovern.config import CC_STATS_CACHE


@dataclass
class StatsCache:
    daily_model_tokens: list[dict] = field(default_factory=list)  # [{date, tokensByModel:{model:int}}]
    daily_activity: list[dict] = field(default_factory=list)
    model_usage: dict[str, dict] = field(default_factory=dict)    # model -> tier 拆分


def load_stats_cache(path: Path = CC_STATS_CACHE) -> StatsCache:
    """讀取 stats-cache.json；缺檔或損毀 → 空 StatsCache（不 raise）。"""
    path = Path(path)
    if not path.exists():
        return StatsCache()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return StatsCache()
    return StatsCache(
        daily_model_tokens=data.get("dailyModelTokens", []) or [],
        daily_activity=data.get("dailyActivity", []) or [],
        model_usage=data.get("modelUsage", {}) or {},
    )


def model_tier_ratios(model_usage: dict[str, dict]) -> dict[str, dict]:
    """各模型的 token tier 比例（all-time），用來把每日合併 tokens 拆回各 tier。

    回傳 {model: {input, output, cache_create, cache_read}}，每個 model 比例和為 1。
    """
    ratios: dict[str, dict] = {}
    for model, mu in model_usage.items():
        inp = int(mu.get("inputTokens", 0) or 0)
        out = int(mu.get("outputTokens", 0) or 0)
        cc = int(mu.get("cacheCreationInputTokens", 0) or 0)
        cr = int(mu.get("cacheReadInputTokens", 0) or 0)
        total = inp + out + cc + cr
        if total <= 0:
            # 沒有資料，全部歸 input（保守），避免除零
            ratios[model] = {"input": 1.0, "output": 0.0, "cache_create": 0.0, "cache_read": 0.0}
            continue
        ratios[model] = {
            "input": inp / total,
            "output": out / total,
            "cache_create": cc / total,
            "cache_read": cr / total,
        }
    return ratios
