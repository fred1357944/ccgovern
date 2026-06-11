"""v0.3 測試：JSONL fallback（stats-cache 過期）與告警。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from ccgovern.collector.jsonl_fallback import (
    UNKNOWN_MODEL,
    build_fallback_daily,
    daily_tier_totals,
    model_shares,
)
from ccgovern.collector.reporter import build_report
from ccgovern.models.governance import Budget, Policy
from ccgovern.models.report import DeveloperReport
from ccgovern.models.usage import DailyUsage, UsageRecord
from ccgovern.server import alerts, ingest, store


def _rec(uuid: str, day: str, inp=100, out=50, cc=200, cr=650) -> UsageRecord:
    return UsageRecord(
        uuid=uuid, timestamp=f"{day}T10:00:00Z", date=day,
        input_tokens=inp, output_tokens=out,
        cache_creation_input_tokens=cc, cache_read_input_tokens=cr,
    )


def test_daily_tier_totals_sums_per_date():
    recs = [_rec("a", "2026-06-01"), _rec("b", "2026-06-01"), _rec("c", "2026-06-02")]
    t = daily_tier_totals(recs)
    assert t["2026-06-01"]["input"] == 200
    assert t["2026-06-02"]["cache_read"] == 650


def test_model_shares_normalized():
    mu = {
        "claude-opus-4-6": {"inputTokens": 0, "outputTokens": 0,
                            "cacheCreationInputTokens": 0, "cacheReadInputTokens": 750},
        "claude-haiku-4-5": {"inputTokens": 250, "outputTokens": 0,
                             "cacheCreationInputTokens": 0, "cacheReadInputTokens": 0},
    }
    s = model_shares(mu)
    assert s["claude-opus-4-6"] == pytest.approx(0.75)
    assert sum(s.values()) == pytest.approx(1.0)


def test_fallback_only_after_cutoff_and_priced():
    recs = [_rec("a", "2026-02-01"), _rec("b", "2026-05-01")]
    mu = {"claude-opus-4-6": {"inputTokens": 100, "outputTokens": 0,
                              "cacheCreationInputTokens": 0, "cacheReadInputTokens": 0}}
    out = build_fallback_daily("d", recs, mu, after_date="2026-02-27")
    assert [du.date for du in out] == ["2026-05-01"]  # cutoff 之前的不重建
    assert out[0].model == "claude-opus-4-6"
    assert out[0].cost_usd > 0


def test_fallback_unknown_model_when_no_stats():
    out = build_fallback_daily("d", [_rec("a", "2026-05-01")], {}, after_date="")
    assert out[0].model == UNKNOWN_MODEL
    assert out[0].cost_usd > 0  # 以預設價計，不歸零


def test_build_report_includes_fallback(tmp_path: Path):
    """stats-cache 停在 2 月，JSONL 有 5 月資料 → 報告應涵蓋到 5 月。"""
    stats = {
        "dailyModelTokens": [{"date": "2026-02-01", "tokensByModel": {"claude-opus-4-6": 1000}}],
        "dailyActivity": [],
        "modelUsage": {"claude-opus-4-6": {"inputTokens": 100, "outputTokens": 50,
                                            "cacheCreationInputTokens": 200,
                                            "cacheReadInputTokens": 650}},
    }
    (tmp_path / "stats.json").write_text(json.dumps(stats))
    proj = tmp_path / "projects" / "p1"
    proj.mkdir(parents=True)
    line = {
        "uuid": "u-may", "timestamp": "2026-05-15T10:00:00Z",
        "toolUseResult": {"totalTokens": 1000,
                          "usage": {"input_tokens": 100, "output_tokens": 50,
                                    "cache_creation_input_tokens": 200,
                                    "cache_read_input_tokens": 650}},
    }
    (proj / "s.jsonl").write_text(json.dumps(line))

    rep = build_report(
        developer_id="d@x",
        projects_dir=tmp_path / "projects",
        stats_path=tmp_path / "stats.json",
        cc_settings_path=tmp_path / "nope.json",
    )
    dates = {du.date for du in rep.daily}
    assert "2026-02-01" in dates
    assert "2026-05-15" in dates       # ← fallback 補上的
    assert rep.date_end == "2026-05-15"


# ---- 告警 ----

def test_alert_lines_for_over_warn_and_violation(tmp_path: Path):
    conn = store.connect(tmp_path / "db.sqlite")
    rep = DeveloperReport(
        developer_id="a@x", machine="m", generated_at="2026-06-10T00:00:00",
        date_start="2026-06-01", date_end="2026-06-01",
        daily=[DailyUsage("a@x", "2026-06-01", "claude-opus-4-6", cost_usd=50.0)],
        settings_snapshot={"mcpServers": ["evil-mcp"], "plugins": []},
    )
    ingest.ingest_report(conn, rep)
    store.set_budget(conn, Budget(scope="dev", target="a@x", monthly_cap_usd=30.0))  # over
    store.set_policy(conn, Policy(blocked_mcp=["evil-mcp"]))

    lines = alerts.build_alert_lines(conn, date(2026, 6, 15))
    text = "\n".join(lines)
    assert "已超支" in text
    assert "evil-mcp" in text
    conn.close()


def test_alert_lines_empty_when_all_ok(tmp_path: Path):
    conn = store.connect(tmp_path / "db.sqlite")
    rep = DeveloperReport(
        developer_id="a@x", machine="m", generated_at="2026-06-10T00:00:00",
        date_start="2026-06-01", date_end="2026-06-01",
        daily=[DailyUsage("a@x", "2026-06-01", "claude-opus-4-6", cost_usd=1.0)],
        settings_snapshot={"mcpServers": [], "plugins": []},
    )
    ingest.ingest_report(conn, rep)
    store.set_budget(conn, Budget(scope="dev", target="a@x", monthly_cap_usd=10000.0))
    assert alerts.build_alert_lines(conn, date(2026, 6, 15)) == []
    conn.close()
