"""政策檢查 — 違規偵測。空 allowlist = 全允許。"""

from __future__ import annotations

import json
import sqlite3

from ccgovern.models.governance import Policy, Violation
from ccgovern.server import store


def check_developer(
    policy: Policy,
    dev_settings: dict,
    used_models: list[str],
    developer_id: str,
) -> list[Violation]:
    violations: list[Violation] = []

    # 模型政策
    if policy.allowed_models:
        for m in used_models:
            if not any(m.startswith(a) or m == a for a in policy.allowed_models):
                violations.append(
                    Violation(developer_id, "model", f"使用未授權模型 {m}", "warning")
                )

    mcp_servers = dev_settings.get("mcpServers", []) or []
    # blocked MCP
    for s in mcp_servers:
        if s in policy.blocked_mcp:
            violations.append(
                Violation(developer_id, "mcp", f"使用被封鎖的 MCP：{s}", "error")
            )
    # allowed MCP（非空才檢查）
    if policy.allowed_mcp:
        for s in mcp_servers:
            if s not in policy.allowed_mcp and s not in policy.blocked_mcp:
                violations.append(
                    Violation(developer_id, "mcp", f"使用未授權 MCP：{s}", "warning")
                )

    # plugin 政策
    if policy.allowed_plugins:
        for p in dev_settings.get("plugins", []) or []:
            if p not in policy.allowed_plugins:
                violations.append(
                    Violation(developer_id, "plugin", f"使用未授權 plugin：{p}", "warning")
                )

    return violations


def check_all(conn: sqlite3.Connection, policy: Policy) -> list[Violation]:
    out: list[Violation] = []
    for dev in store.distinct_developers(conn):
        did = dev["developer_id"]
        try:
            settings = json.loads(dev["settings_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            settings = {}
        used = store.developer_models(conn, did)
        out.extend(check_developer(policy, settings, used, did))
    return out
