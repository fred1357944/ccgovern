"""預算評估 — today 由呼叫端注入，純函式可測。"""

from __future__ import annotations

import calendar
import sqlite3
from dataclasses import dataclass
from datetime import date

from ccgovern.models.governance import Budget
from ccgovern.server import aggregate


@dataclass
class BudgetStatus:
    budget: Budget
    cap: float
    spent: float
    projected: float
    pct_of_cap: float
    projected_pct: float
    alert: bool
    level: str  # "ok" | "warn" | "over"


def month_spend(conn: sqlite3.Connection, scope: str, target: str, month: str) -> float:
    if scope == "team":
        return aggregate.team_totals(conn, month)["total_cost"]
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) AS c FROM daily_usage WHERE developer_id = ? AND date LIKE ?",
        (target, f"{month}%"),
    ).fetchone()
    return row["c"]


def projected_spend(today_spend: float, day_of_month: int, days_in_month: int) -> float:
    """線性外推到月底。"""
    if day_of_month <= 0:
        return today_spend
    return today_spend / day_of_month * days_in_month


def evaluate_budget(conn: sqlite3.Connection, budget: Budget, today: date) -> BudgetStatus:
    month = today.strftime("%Y-%m")
    spent = month_spend(conn, budget.scope, budget.target, month)
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    projected = projected_spend(spent, today.day, days_in_month)
    cap = budget.monthly_cap_usd
    pct = (spent / cap) if cap > 0 else 0.0
    ppct = (projected / cap) if cap > 0 else 0.0
    if spent >= cap and cap > 0:
        level = "over"
    elif ppct >= budget.alert_threshold:
        level = "warn"
    else:
        level = "ok"
    return BudgetStatus(
        budget=budget, cap=cap, spent=spent, projected=projected,
        pct_of_cap=pct, projected_pct=ppct,
        alert=(level != "ok"), level=level,
    )


def evaluate_all(conn: sqlite3.Connection, today: date) -> list[BudgetStatus]:
    from ccgovern.server import store
    return [evaluate_budget(conn, b, today) for b in store.get_budgets(conn)]
