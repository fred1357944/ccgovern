"""Atomic JSON 寫檔 + 備份 — 取自 DevDeck cc_config_service 的安全寫入模式。"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path


def backup_file(path: Path) -> Path | None:
    """備份檔案，回傳備份路徑。檔案不存在或備份失敗時回傳 None。"""
    if not path.exists():
        return None
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = path.with_suffix(path.suffix + f".bak-{ts}")
    try:
        shutil.copy2(path, bak)
        return bak
    except OSError:
        return None


def atomic_write_json(path: Path, obj: object, backup: bool = False) -> tuple[bool, str]:
    """原子化寫入 JSON：先（可選）備份，寫入 temp 檔再 os.replace。

    回傳 (成功, 訊息)。若 backup=True 且原檔存在但備份失敗，拒絕寫入。
    """
    path = Path(path)
    if backup and path.exists():
        if backup_file(path) is None:
            return False, f"備份 {path.name} 失敗，拒絕寫入"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False, indent=2))
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except OSError as e:
        return False, f"寫入 {path.name} 失敗：{e}"
    return True, "ok"
