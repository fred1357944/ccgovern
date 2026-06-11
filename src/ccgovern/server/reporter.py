"""彙整本機資料 → DeveloperReport（可上傳）。

策略 A：每日趨勢用 dailyModelTokens（日×模型合併 tokens）套各模型 all-time tier
比例拆分成 DailyUsage 各 tier，再算成本。每日為「估算」；總成本以 modelUsage 為準。
"""

from __future__ import annotations

import getpass
import json
import socket
import subprocess
from pathlib import Path

from ccgovern.collector import pricing
from ccgovern.collector.stats_cache_parser import (
    StatsCache,
    load_stats_cache,
    model_tier_ratios,
)
from ccgovern.config import CC_PROJECTS_DIR, CC_SETTINGS_FILE, CC_STATS_CACHE
from ccgovern.models.report import DeveloperReport
from ccgovern.models.usage import DailyUsage
from ccgovern.util.atomic_io import atomic_write_json


def resolve_developer_id() -> str:
    """穩定鍵：git config user.email → 退回 user@hostname。"""
    try:
        out = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, timeout=5,
        )
        email = out.stdout.strip()
        if email:
            return email
    except (subprocess.SubprocessError, OSError):
        pass
    try:
        return f"{getpass.getuser()}@{socket.gethostname()}"
    except Exception:
        return "unknown"


def _read_settings_snapshot(path: Path = CC_SETTINGS_FILE) -> dict:
    """讀取本機 settings.json，擷取 mcpServers / plugins（政策檢查用）。"""
    path = Path(path)
    if not path.exists():
        return {"mcpServers": [], "plugins": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"mcpServers": [], "plugins": []}
    mcp = sorted((data.get("mcpServers") or {}).keys())
    plugins = sorted(k for k, v in (data.get("enabledPlugins") or {}).items() if v)
    return {"mcpServers": mcp, "plugins": plugins}


def build_daily_usage(developer_id: str, stats: StatsCache) -> list[DailyUsage]:
    """把 dailyModelTokens 用 all-time tier 比例拆成 DailyUsage（策略 A）。"""
    ratios = model_tier_ratios(stats.model_usage)
    out: list[DailyUsage] = []
    for entry in stats.daily_model_tokens:
        date = entry.get("date", "")
        by_model = entry.get("tokensByModel", {}) or {}
        for model, combined in by_model.items():
            combined = int(combined or 0)
            if combined <= 0:
                continue
            r = ratios.get(model, {"input": 1.0, "output": 0.0, "cache_create": 0.0, "cache_read": 0.0})
            du = DailyUsage(
                developer_id=developer_id,
                date=date,
                model=model,
                input_tokens=round(combined * r["input"]),
                output_tokens=round(combined * r["output"]),
                cache_creation_input_tokens=round(combined * r["cache_create"]),
                cache_read_input_tokens=round(combined * r["cache_read"]),
            )
            du.cost_usd = pricing.compute_cost(du)
            out.append(du)
    return out


def build_report(
    developer_id: str | None = None,
    projects_dir: Path = CC_PROJECTS_DIR,
    stats_path: Path = CC_STATS_CACHE,
    cc_settings_path: Path = CC_SETTINGS_FILE,
    generated_at: str = "",
) -> DeveloperReport:
    """組出一份 DeveloperReport。generated_at 由呼叫端傳入（避免在此取系統時間）。"""
    dev = developer_id or resolve_developer_id()
    stats = load_stats_cache(stats_path)
    daily = build_daily_usage(dev, stats)

    # 策略 B fallback：stats-cache 可能過期（CC 內部快取停更）。
    # 對其涵蓋日之後的日期，直接從 JSONL 重建（tier 精確、模型為估算拆分）。
    from ccgovern.collector.jsonl_fallback import build_fallback_daily
    from ccgovern.collector.jsonl_parser import parse_all
    stats_max = max((du.date for du in daily), default="")
    records = parse_all(projects_dir)
    daily += build_fallback_daily(dev, records, stats.model_usage, after_date=stats_max)

    total_cost = sum(du.cost_usd for du in daily)
    dates = sorted(du.date for du in daily if du.date)
    snapshot = _read_settings_snapshot(cc_settings_path)
    snapshot["models"] = sorted(stats.model_usage.keys())
    return DeveloperReport(
        developer_id=dev,
        machine=_safe_hostname(),
        generated_at=generated_at,
        date_start=dates[0] if dates else "",
        date_end=dates[-1] if dates else "",
        daily=daily,
        total_cost_usd=total_cost,
        settings_snapshot=snapshot,
    )


def _safe_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return ""


def safe_developer_filename(developer_id: str) -> str:
    """把 developer_id 轉成安全檔名 stem：只留白名單字元，杜絕路徑穿越。

    任何 / \\ .. 等都會被剝除，輸出絕不含路徑分隔符。空字串退回 'unknown'。
    """
    import re
    stem = developer_id.replace("@", "_at_")
    stem = re.sub(r"[^A-Za-z0-9._+-]", "_", stem)  # 白名單；其餘（含 / \ 空白）→ _
    stem = stem.lstrip(".")                          # 去開頭點，避免 .. / 隱藏檔
    return stem[:128] or "unknown"


def save_report(report: DeveloperReport, out_dir: Path) -> Path:
    """把報告寫入 ingest 目錄（atomic）。檔名由 developer_id 消毒後產生。"""
    import os
    out_dir = Path(out_dir).resolve()
    path = (out_dir / f"{safe_developer_filename(report.developer_id)}.json").resolve()
    # 縱深防禦：確認最終路徑仍在 out_dir 內
    if not str(path).startswith(str(out_dir) + os.sep):
        raise ValueError("路徑逃逸：developer_id 產生了 out_dir 以外的路徑")
    atomic_write_json(path, report.to_dict(), backup=False)
    return path
