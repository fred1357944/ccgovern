"""匯入 DeveloperReport JSON → SQLite。檔案目錄 ingest 是未來 HTTP 端點的替身。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ccgovern.models.report import DeveloperReport
from ccgovern.server import store


def ingest_report(conn: sqlite3.Connection, report: DeveloperReport) -> str:
    """把一份已解析的報告寫入 store（replace 模式，idempotent）。"""
    store.upsert_developer(
        conn,
        developer_id=report.developer_id,
        machine=report.machine,
        last_active=report.date_end,
        settings_snapshot=report.settings_snapshot,
        updated_at=report.generated_at,
    )
    store.replace_developer_usage(conn, report.developer_id, report.daily)
    return report.developer_id


def ingest_file(conn: sqlite3.Connection, path: Path) -> str | None:
    """讀單一報告檔並匯入；壞檔略過回傳 None。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or not data.get("developer_id"):
        return None
    return ingest_report(conn, DeveloperReport.from_dict(data))


def ingest_dir(conn: sqlite3.Connection, ingest_dir: Path) -> list[str]:
    """匯入目錄下所有 *.json，回傳成功匯入的開發者 id。"""
    ingest_dir = Path(ingest_dir)
    if not ingest_dir.is_dir():
        return []
    done: list[str] = []
    for path in sorted(ingest_dir.glob("*.json")):
        dev = ingest_file(conn, path)
        if dev:
            done.append(dev)
    return done
