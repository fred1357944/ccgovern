"""模型定價與成本計算。2026 價格，per 1M tokens。

成本未儲存於 Claude Code 資料中（costUSD 恆 0），一律由此計算。
cache_read ≈ input 價 0.1×；cache_creation(5m TTL) ≈ input 價 1.25×。
定價集中於此一處，便於更新（驗證來源：claude-api skill, 2026-06）。
"""

from __future__ import annotations

from dataclasses import dataclass

CACHE_READ_MULTIPLIER = 0.10
CACHE_WRITE_MULTIPLIER = 1.25


@dataclass(frozen=True)
class ModelPrice:
    input: float   # USD per 1M input tokens
    output: float  # USD per 1M output tokens


# 鍵為「正規化前綴」，resolve_model 以最長前綴比對完整 id
PRICING: dict[str, ModelPrice] = {
    "claude-opus-4": ModelPrice(input=5.0, output=25.0),
    "claude-sonnet-4": ModelPrice(input=3.0, output=15.0),
    "claude-haiku-4": ModelPrice(input=1.0, output=5.0),
    "claude-fable-5": ModelPrice(input=10.0, output=50.0),
}
DEFAULT_PRICE = ModelPrice(input=5.0, output=25.0)  # 未知模型退回 Opus 價，不 crash


def resolve_model(model_id: str) -> ModelPrice:
    """以最長前綴比對完整模型 id（如 claude-opus-4-5-20251101 → claude-opus-4）。"""
    best: ModelPrice | None = None
    best_len = -1
    for prefix, price in PRICING.items():
        if model_id.startswith(prefix) and len(prefix) > best_len:
            best = price
            best_len = len(prefix)
    return best if best is not None else DEFAULT_PRICE


def compute_cost_tiers(
    model: str,
    input_t: int,
    output_t: int,
    cache_create_t: int,
    cache_read_t: int,
) -> float:
    """依各 token tier 計算成本（USD）。"""
    p = resolve_model(model)
    cost = (
        input_t * p.input
        + output_t * p.output
        + cache_create_t * p.input * CACHE_WRITE_MULTIPLIER
        + cache_read_t * p.input * CACHE_READ_MULTIPLIER
    )
    return cost / 1_000_000


def compute_cost(du) -> float:  # du: DailyUsage（避免循環 import 不標型別）
    return compute_cost_tiers(
        du.model,
        du.input_tokens,
        du.output_tokens,
        du.cache_creation_input_tokens,
        du.cache_read_input_tokens,
    )
