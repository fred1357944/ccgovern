"""策略 B fallback — 當 stats-cache 過期時，直接從 JSONL 重建每日用量。

問題：stats-cache.json 是 Claude Code 內部快取，可能停止更新（實測本機停在數月前），
導致 stats-cache 之後的用量全部漏掉。

解法：JSONL 有精確的每日 tier（input/output/cache_create/cache_read）但**無模型名**。
對 stats-cache 涵蓋日之後的日期，把 JSONL 的 tier 總量依 all-time 模型佔比拆給各模型
（modelUsage 的合併 token 份額）。模型維度為估算，tier 與總量為精確。
"""

from __future__ import annotations

from collections import defaultdict

from ccgovern.collector import pricing
from ccgovern.models.usage import DailyUsage, UsageRecord

UNKNOWN_MODEL = "unattributed"


def daily_tier_totals(records: list[UsageRecord]) -> dict[str, dict[str, int]]:
    """JSONL 記錄 → {date: {input, output, cache_create, cache_read}}（精確）。"""
    out: dict[str, dict[str, int]] = defaultdict(
        lambda: {"input": 0, "output": 0, "cache_create": 0, "cache_read": 0}
    )
    for r in records:
        if not r.date:
            continue
        d = out[r.date]
        d["input"] += r.input_tokens
        d["output"] += r.output_tokens
        d["cache_create"] += r.cache_creation_input_tokens
        d["cache_read"] += r.cache_read_input_tokens
    return dict(out)


def model_shares(model_usage: dict[str, dict]) -> dict[str, float]:
    """all-time 各模型的合併 token 份額（用來把無模型名的日量拆給模型）。"""
    combined: dict[str, int] = {}
    for model, mu in model_usage.items():
        combined[model] = (
            int(mu.get("inputTokens", 0) or 0)
            + int(mu.get("outputTokens", 0) or 0)
            + int(mu.get("cacheCreationInputTokens", 0) or 0)
            + int(mu.get("cacheReadInputTokens", 0) or 0)
        )
    total = sum(combined.values())
    if total <= 0:
        return {}
    return {m: c / total for m, c in combined.items() if c > 0}


def build_fallback_daily(
    developer_id: str,
    records: list[UsageRecord],
    model_usage: dict[str, dict],
    after_date: str,
) -> list[DailyUsage]:
    """為 after_date（不含）之後的日期，從 JSONL 重建 DailyUsage。

    模型拆分依 all-time 份額；無任何模型資訊時整筆掛 UNKNOWN_MODEL（以預設價計）。
    """
    tiers_by_date = daily_tier_totals(records)
    shares = model_shares(model_usage) or {UNKNOWN_MODEL: 1.0}
    out: list[DailyUsage] = []
    for date_str in sorted(tiers_by_date):
        if after_date and date_str <= after_date:
            continue
        t = tiers_by_date[date_str]
        for model, share in shares.items():
            du = DailyUsage(
                developer_id=developer_id,
                date=date_str,
                model=model,
                input_tokens=round(t["input"] * share),
                output_tokens=round(t["output"] * share),
                cache_creation_input_tokens=round(t["cache_create"] * share),
                cache_read_input_tokens=round(t["cache_read"] * share),
            )
            if du.total_tokens <= 0:
                continue
            du.cost_usd = pricing.compute_cost(du)
            out.append(du)
    return out
