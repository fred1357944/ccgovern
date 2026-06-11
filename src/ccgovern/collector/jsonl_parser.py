"""解析 ~/.claude/projects/**/*.jsonl 用量記錄。純 Python，逐行容錯。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from ccgovern.config import CC_PROJECTS_DIR
from ccgovern.models.usage import UsageRecord


def parse_jsonl_file(path: Path) -> Iterator[UsageRecord]:
    """逐行解析單一檔案；壞行略過，不讓一行壞掉整個檔案。"""
    try:
        f = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            tur = rec.get("toolUseResult")
            if not isinstance(tur, dict):
                continue
            usage = tur.get("usage")
            if not isinstance(usage, dict):
                continue
            uuid = rec.get("uuid")
            if not uuid:
                continue  # 無 uuid 無法安全去重
            ts = rec.get("timestamp", "")
            yield UsageRecord(
                uuid=uuid,
                timestamp=ts,
                date=ts[:10] if len(ts) >= 10 else "",
                session_id=rec.get("sessionId", ""),
                cwd=rec.get("cwd", ""),
                git_branch=rec.get("gitBranch", ""),
                version=rec.get("version", ""),
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
                cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens", 0) or 0),
                cache_read_input_tokens=int(usage.get("cache_read_input_tokens", 0) or 0),
                total_tokens=int(tur.get("totalTokens", 0) or 0),
            )


def parse_all(projects_dir: Path = CC_PROJECTS_DIR) -> list[UsageRecord]:
    """掃描所有 *.jsonl，解析並以 uuid 去重（後者覆蓋前者）。"""
    projects_dir = Path(projects_dir)
    if not projects_dir.is_dir():
        return []
    seen: dict[str, UsageRecord] = {}
    for path in projects_dir.rglob("*.jsonl"):
        for rec in parse_jsonl_file(path):
            seen[rec.uuid] = rec
    return list(seen.values())
