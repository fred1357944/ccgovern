"""SQLite 儲存層。PK (developer_id, date, model) 保證重 ingest idempotent。

資料模型為 HTTP-ready：未來的上傳端點可呼叫同樣的 upsert。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ccgovern.config import DB_FILE
from ccgovern.models.governance import Budget, Policy
from ccgovern.models.usage import DailyUsage


def connect(db_path: Path = DB_FILE, same_thread: bool = True) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # same_thread=False 供 TUI 用：背景 @work 執行緒會用到同一連線；
    # 因 reingest worker 為 exclusive（序列化），不會有並發寫入。
    conn = sqlite3.connect(str(db_path), check_same_thread=same_thread)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS developers (
            developer_id TEXT PRIMARY KEY,
            machine TEXT,
            last_active TEXT,
            settings_json TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS daily_usage (
            developer_id TEXT,
            date TEXT,
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cache_creation_input_tokens INTEGER,
            cache_read_input_tokens INTEGER,
            cost_usd REAL,
            PRIMARY KEY (developer_id, date, model)
        );
        CREATE TABLE IF NOT EXISTS budgets (
            scope TEXT,
            target TEXT,
            monthly_cap_usd REAL,
            alert_threshold REAL,
            PRIMARY KEY (scope, target)
        );
        CREATE TABLE IF NOT EXISTS policies (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            allowed_models TEXT,
            allowed_mcp TEXT,
            blocked_mcp TEXT,
            allowed_plugins TEXT
        );
        """
    )
    conn.commit()


def upsert_developer(
    conn: sqlite3.Connection,
    developer_id: str,
    machine: str,
    last_active: str,
    settings_snapshot: dict,
    updated_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO developers (developer_id, machine, last_active, settings_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(developer_id) DO UPDATE SET
            machine=excluded.machine,
            last_active=excluded.last_active,
            settings_json=excluded.settings_json,
            updated_at=excluded.updated_at
        """,
        (developer_id, machine, last_active, json.dumps(settings_snapshot, ensure_ascii=False), updated_at),
    )


def replace_developer_usage(conn: sqlite3.Connection, developer_id: str, daily: list[DailyUsage]) -> None:
    """刪除該開發者既有 usage，重新插入 — 保證重 ingest idempotent。"""
    conn.execute("DELETE FROM daily_usage WHERE developer_id = ?", (developer_id,))
    conn.executemany(
        """
        INSERT INTO daily_usage
            (developer_id, date, model, input_tokens, output_tokens,
             cache_creation_input_tokens, cache_read_input_tokens, cost_usd)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                du.developer_id, du.date, du.model,
                du.input_tokens, du.output_tokens,
                du.cache_creation_input_tokens, du.cache_read_input_tokens,
                du.cost_usd,
            )
            for du in daily
        ],
    )
    conn.commit()


def distinct_developers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM developers ORDER BY developer_id"))


def developer_row(conn: sqlite3.Connection, developer_id: str) -> sqlite3.Row | None:
    cur = conn.execute("SELECT * FROM developers WHERE developer_id = ?", (developer_id,))
    return cur.fetchone()


def all_daily_usage(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute("SELECT * FROM daily_usage"))


def developer_daily(conn: sqlite3.Connection, developer_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM daily_usage WHERE developer_id = ? ORDER BY date", (developer_id,)
        )
    )


def developer_models(conn: sqlite3.Connection, developer_id: str) -> list[str]:
    return [
        r["model"]
        for r in conn.execute(
            "SELECT DISTINCT model FROM daily_usage WHERE developer_id = ?", (developer_id,)
        )
    ]


# ---- 預算 ----

def set_budget(conn: sqlite3.Connection, budget: Budget) -> None:
    conn.execute(
        """
        INSERT INTO budgets (scope, target, monthly_cap_usd, alert_threshold)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(scope, target) DO UPDATE SET
            monthly_cap_usd=excluded.monthly_cap_usd,
            alert_threshold=excluded.alert_threshold
        """,
        (budget.scope, budget.target, budget.monthly_cap_usd, budget.alert_threshold),
    )
    conn.commit()


def get_budgets(conn: sqlite3.Connection) -> list[Budget]:
    return [
        Budget(
            scope=r["scope"], target=r["target"],
            monthly_cap_usd=r["monthly_cap_usd"], alert_threshold=r["alert_threshold"],
        )
        for r in conn.execute("SELECT * FROM budgets")
    ]


def get_budget(conn: sqlite3.Connection, scope: str, target: str) -> Budget | None:
    r = conn.execute(
        "SELECT * FROM budgets WHERE scope = ? AND target = ?", (scope, target)
    ).fetchone()
    if r is None:
        return None
    return Budget(
        scope=r["scope"], target=r["target"],
        monthly_cap_usd=r["monthly_cap_usd"], alert_threshold=r["alert_threshold"],
    )


# ---- 政策 ----

def set_policy(conn: sqlite3.Connection, policy: Policy) -> None:
    conn.execute(
        """
        INSERT INTO policies (id, allowed_models, allowed_mcp, blocked_mcp, allowed_plugins)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            allowed_models=excluded.allowed_models,
            allowed_mcp=excluded.allowed_mcp,
            blocked_mcp=excluded.blocked_mcp,
            allowed_plugins=excluded.allowed_plugins
        """,
        (
            json.dumps(policy.allowed_models, ensure_ascii=False),
            json.dumps(policy.allowed_mcp, ensure_ascii=False),
            json.dumps(policy.blocked_mcp, ensure_ascii=False),
            json.dumps(policy.allowed_plugins, ensure_ascii=False),
        ),
    )
    conn.commit()


def get_policy(conn: sqlite3.Connection) -> Policy:
    r = conn.execute("SELECT * FROM policies WHERE id = 1").fetchone()
    if r is None:
        return Policy()
    return Policy(
        allowed_models=json.loads(r["allowed_models"] or "[]"),
        allowed_mcp=json.loads(r["allowed_mcp"] or "[]"),
        blocked_mcp=json.loads(r["blocked_mcp"] or "[]"),
        allowed_plugins=json.loads(r["allowed_plugins"] or "[]"),
    )
