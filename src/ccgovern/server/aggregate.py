"""彙總分析 — 純讀，TUI 全靠它。月份過濾用 date LIKE 'YYYY-MM%'。"""

from __future__ import annotations

import sqlite3

from ccgovern.models.report import DeveloperSummary
from ccgovern.server import store


def _month_clause(month: str | None) -> tuple[str, list]:
    if month:
        return " AND date LIKE ?", [f"{month}%"]
    return "", []


def team_totals(conn: sqlite3.Connection, month: str | None = None) -> dict:
    clause, params = _month_clause(month)
    row = conn.execute(
        f"""
        SELECT COALESCE(SUM(cost_usd), 0) AS cost,
               COALESCE(SUM(input_tokens + output_tokens
                            + cache_creation_input_tokens + cache_read_input_tokens), 0) AS tokens,
               COUNT(DISTINCT developer_id) AS devs
        FROM daily_usage WHERE 1=1{clause}
        """,
        params,
    ).fetchone()
    by_model = by_model_costs(conn, month)
    return {
        "total_cost": row["cost"],
        "total_tokens": row["tokens"],
        "dev_count": row["devs"],
        "by_model": by_model,
    }


def by_model_costs(conn: sqlite3.Connection, month: str | None = None) -> dict[str, dict]:
    clause, params = _month_clause(month)
    rows = conn.execute(
        f"""
        SELECT model,
               SUM(cost_usd) AS cost,
               SUM(input_tokens + output_tokens
                   + cache_creation_input_tokens + cache_read_input_tokens) AS tokens
        FROM daily_usage WHERE 1=1{clause}
        GROUP BY model ORDER BY cost DESC
        """,
        params,
    ).fetchall()
    return {r["model"]: {"cost": r["cost"] or 0.0, "tokens": r["tokens"] or 0} for r in rows}


def developer_summaries(conn: sqlite3.Connection, month: str | None = None) -> list[DeveloperSummary]:
    out: list[DeveloperSummary] = []
    for dev in store.distinct_developers(conn):
        did = dev["developer_id"]
        total = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) AS c FROM daily_usage WHERE developer_id = ?", (did,)
        ).fetchone()["c"]
        clause, params = _month_clause(month)
        mcost = conn.execute(
            f"SELECT COALESCE(SUM(cost_usd),0) AS c FROM daily_usage WHERE developer_id = ?{clause}",
            [did, *params],
        ).fetchone()["c"]
        top = conn.execute(
            """
            SELECT model FROM daily_usage WHERE developer_id = ?
            GROUP BY model ORDER BY SUM(cost_usd) DESC LIMIT 1
            """,
            (did,),
        ).fetchone()
        out.append(
            DeveloperSummary(
                developer_id=did,
                machine=dev["machine"] or "",
                total_cost_usd=total,
                month_cost_usd=mcost,
                top_model=(top["model"] if top else "—"),
                last_active=dev["last_active"] or "",
            )
        )
    return sorted(out, key=lambda s: s.month_cost_usd, reverse=True)


def developer_detail(conn: sqlite3.Connection, developer_id: str) -> dict:
    daily = conn.execute(
        """
        SELECT date, SUM(cost_usd) AS cost FROM daily_usage
        WHERE developer_id = ? GROUP BY date ORDER BY date
        """,
        (developer_id,),
    ).fetchall()
    by_model = conn.execute(
        """
        SELECT model,
               SUM(cost_usd) AS cost,
               SUM(input_tokens + output_tokens
                   + cache_creation_input_tokens + cache_read_input_tokens) AS tokens
        FROM daily_usage WHERE developer_id = ?
        GROUP BY model ORDER BY cost DESC
        """,
        (developer_id,),
    ).fetchall()
    return {
        "daily_trend": [(r["date"], r["cost"] or 0.0) for r in daily],
        "by_model": {r["model"]: {"cost": r["cost"] or 0.0, "tokens": r["tokens"] or 0} for r in by_model},
    }


def team_trend(conn: sqlite3.Connection) -> list[tuple[str, float]]:
    rows = conn.execute(
        "SELECT date, SUM(cost_usd) AS cost FROM daily_usage GROUP BY date ORDER BY date"
    ).fetchall()
    return [(r["date"], r["cost"] or 0.0) for r in rows]
