"""pure-Python 測試：pricing / parsers / models / aggregate / budget / policy。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ccgovern.collector import pricing
from ccgovern.collector.jsonl_parser import parse_all, parse_jsonl_file
from ccgovern.collector.stats_cache_parser import load_stats_cache, model_tier_ratios
from ccgovern.models.governance import Budget, Policy
from ccgovern.models.report import DeveloperReport
from ccgovern.models.usage import DailyUsage, UsageRecord
from ccgovern.server import aggregate, budget, ingest, policy, store


# ---- pricing ----

def test_resolve_model_longest_prefix():
    assert pricing.resolve_model("claude-opus-4-5-20251101").input == 5.0
    assert pricing.resolve_model("claude-sonnet-4-5-20250929").input == 3.0
    assert pricing.resolve_model("claude-haiku-4-5-20251001").input == 1.0


def test_unknown_model_falls_back_no_crash():
    p = pricing.resolve_model("claude-unknown-9")
    assert p.input > 0  # 回退預設，不 crash


def test_cost_tiers_math():
    # 1M input on opus = $5；1M output = $25；1M cache_read = $0.5；1M cache_create = $6.25
    cost = pricing.compute_cost_tiers("claude-opus-4-6", 1_000_000, 0, 0, 0)
    assert cost == pytest.approx(5.0)
    cost = pricing.compute_cost_tiers("claude-opus-4-6", 0, 1_000_000, 0, 0)
    assert cost == pytest.approx(25.0)
    cost = pricing.compute_cost_tiers("claude-opus-4-6", 0, 0, 0, 1_000_000)
    assert cost == pytest.approx(0.5)   # cache_read 0.1×
    cost = pricing.compute_cost_tiers("claude-opus-4-6", 0, 0, 1_000_000, 0)
    assert cost == pytest.approx(6.25)  # cache_write 1.25×


# ---- jsonl parser ----

def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")


def test_jsonl_skips_malformed_and_dedupes(tmp_path: Path):
    p = tmp_path / "a.jsonl"
    good = {
        "uuid": "u1", "timestamp": "2026-06-01T10:00:00Z", "sessionId": "s1",
        "toolUseResult": {"totalTokens": 100, "usage": {"input_tokens": 10, "output_tokens": 5}},
    }
    dup = {**good}  # 同 uuid → 去重後一筆
    no_usage = {"uuid": "u2", "timestamp": "2026-06-01T10:00:00Z", "toolUseResult": {}}
    p.write_text(
        json.dumps(good) + "\n{ broken json\n" + json.dumps(dup) + "\n" + json.dumps(no_usage) + "\n",
        encoding="utf-8",
    )
    recs = list(parse_jsonl_file(p))
    assert len(recs) == 2  # good 出現兩次（同檔不去重），no_usage 被濾掉、壞行略過
    # parse_all 跨檔以 uuid 去重
    deduped = parse_all(tmp_path)
    assert len([r for r in deduped if r.uuid == "u1"]) == 1


def test_jsonl_derives_date():
    rec = UsageRecord(uuid="x", timestamp="2026-06-11T08:00:00Z", date="2026-06-11")
    assert rec.date == "2026-06-11"


# ---- stats cache ----

def test_stats_cache_list_shaped(tmp_path: Path):
    data = {
        "dailyModelTokens": [{"date": "2026-06-01", "tokensByModel": {"claude-opus-4-6": 1000}}],
        "dailyActivity": [{"date": "2026-06-01", "messageCount": 5}],
        "modelUsage": {"claude-opus-4-6": {"inputTokens": 100, "outputTokens": 50,
                                            "cacheCreationInputTokens": 200, "cacheReadInputTokens": 650}},
    }
    p = tmp_path / "stats-cache.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    sc = load_stats_cache(p)
    assert isinstance(sc.daily_model_tokens, list)
    ratios = model_tier_ratios(sc.model_usage)
    r = ratios["claude-opus-4-6"]
    assert pytest.approx(sum(r.values())) == 1.0


def test_stats_cache_missing_file_returns_empty(tmp_path: Path):
    sc = load_stats_cache(tmp_path / "nope.json")
    assert sc.model_usage == {}


# ---- models roundtrip ----

def test_report_roundtrip_nested():
    du = DailyUsage(developer_id="d", date="2026-06-01", model="claude-opus-4-6",
                    input_tokens=10, cost_usd=1.5)
    rep = DeveloperReport(developer_id="d", machine="m", daily=[du], total_cost_usd=1.5)
    rep2 = DeveloperReport.from_dict(rep.to_dict())
    assert rep2.developer_id == "d"
    assert len(rep2.daily) == 1
    assert rep2.daily[0].model == "claude-opus-4-6"
    assert rep2.daily[0].cost_usd == 1.5


# ---- aggregate (multi-dev) ----

def _seed_two_devs(conn):
    rep_a = DeveloperReport(
        developer_id="a@x", machine="ma", generated_at="2026-06-20T00:00:00",
        date_start="2026-06-01", date_end="2026-06-02",
        daily=[
            DailyUsage("a@x", "2026-06-01", "claude-opus-4-6", cost_usd=10.0),
            DailyUsage("a@x", "2026-06-02", "claude-opus-4-6", cost_usd=20.0),
        ],
        settings_snapshot={"mcpServers": ["context7"], "plugins": []},
    )
    rep_b = DeveloperReport(
        developer_id="b@x", machine="mb", generated_at="2026-06-20T00:00:00",
        date_start="2026-06-01", date_end="2026-06-01",
        daily=[DailyUsage("b@x", "2026-06-01", "claude-haiku-4-5", cost_usd=5.0)],
        settings_snapshot={"mcpServers": ["chrome-devtools"], "plugins": []},
    )
    ingest.ingest_report(conn, rep_a)
    ingest.ingest_report(conn, rep_b)


def test_aggregate_team_totals(tmp_path: Path):
    conn = store.connect(tmp_path / "db.sqlite")
    _seed_two_devs(conn)
    totals = aggregate.team_totals(conn, month="2026-06")
    assert totals["dev_count"] == 2
    assert totals["total_cost"] == pytest.approx(35.0)
    summaries = aggregate.developer_summaries(conn, month="2026-06")
    assert len(summaries) == 2
    assert summaries[0].developer_id == "a@x"  # 花費最高排前


def test_ingest_idempotent(tmp_path: Path):
    conn = store.connect(tmp_path / "db.sqlite")
    _seed_two_devs(conn)
    _seed_two_devs(conn)  # 再 ingest 一次
    totals = aggregate.team_totals(conn, month="2026-06")
    assert totals["total_cost"] == pytest.approx(35.0)  # 不重複累加


# ---- budget ----

def test_budget_projection_and_levels(tmp_path: Path):
    conn = store.connect(tmp_path / "db.sqlite")
    _seed_two_devs(conn)  # a@x 本月 30.0
    b = Budget(scope="dev", target="a@x", monthly_cap_usd=100.0, alert_threshold=0.8)
    # 第 6 天花了 30 → 預估月底 30/6*30 = 150 → 超過 80% 上限 → warn
    status = budget.evaluate_budget(conn, b, date(2026, 6, 6))
    assert status.level == "warn"
    # 上限拉高，預估不超 → ok
    b2 = Budget(scope="dev", target="a@x", monthly_cap_usd=1000.0, alert_threshold=0.8)
    assert budget.evaluate_budget(conn, b2, date(2026, 6, 6)).level == "ok"


def test_budget_over_when_spent_exceeds_cap(tmp_path: Path):
    conn = store.connect(tmp_path / "db.sqlite")
    _seed_two_devs(conn)
    b = Budget(scope="dev", target="a@x", monthly_cap_usd=10.0)  # 已花 30 > 10
    assert budget.evaluate_budget(conn, b, date(2026, 6, 15)).level == "over"


# ---- policy ----

def test_policy_blocked_mcp_flagged():
    pol = Policy(blocked_mcp=["chrome-devtools"])
    v = policy.check_developer(pol, {"mcpServers": ["chrome-devtools", "context7"]}, [], "d")
    assert any(x.kind == "mcp" and x.severity == "error" for x in v)


def test_policy_unallowed_model_flagged():
    pol = Policy(allowed_models=["claude-sonnet-4-5"])
    v = policy.check_developer(pol, {}, ["claude-opus-4-6"], "d")
    assert any(x.kind == "model" for x in v)


def test_policy_empty_allowlist_no_violation():
    pol = Policy()
    v = policy.check_developer(pol, {"mcpServers": ["anything"]}, ["any-model"], "d")
    assert v == []


def test_policy_check_all_reads_snapshot(tmp_path: Path):
    conn = store.connect(tmp_path / "db.sqlite")
    _seed_two_devs(conn)
    pol = Policy(blocked_mcp=["chrome-devtools"])
    violations = policy.check_all(conn, pol)
    assert any(v.developer_id == "b@x" for v in violations)  # b@x 用了 chrome-devtools
