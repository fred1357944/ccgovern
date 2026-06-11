"""產生可信的假團隊資料（4 位開發者），含 1 個預算告警 + 1 個政策違規。

成本透過真實 pricing.py 計算，數字與 dashboard 自洽。
無亂數依賴（不可用 Math.random / Date.now），改用 index 變化 + 固定種子序列。
"""

from __future__ import annotations

import time
from pathlib import Path

from ccgovern.collector import pricing
from ccgovern.config import DB_FILE, INGEST_DIR
from ccgovern.models.governance import Budget, Policy
from ccgovern.models.report import DeveloperReport
from ccgovern.models.usage import DailyUsage
from ccgovern.server import ingest, store

FAKE_DEVS = [
    ("alice@team.dev", "alice-mbp"),
    ("bob@team.dev", "bob-linux"),
    ("carol@team.dev", "carol-mbp"),
    ("dave@team.dev", "dave-wsl"),
]

MODELS = [
    "claude-opus-4-6",
    "claude-opus-4-5-20251101",
    "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5-20251001",
]

# 各開發者的「模型偏好權重」與「日用量規模」，刻意拉開成本差異
DEV_PROFILE = {
    "alice@team.dev": {"models": [0, 1], "scale": 1.0},   # opus 重用戶 → 高成本
    "bob@team.dev":   {"models": [2, 3], "scale": 0.5},   # sonnet/haiku → 低成本
    "carol@team.dev": {"models": [1, 2], "scale": 0.7},
    "dave@team.dev":  {"models": [0], "scale": 1.6},      # opus 狂用 → 會觸發預算告警
}

# 偽隨機序列（固定，無 random），用 index 取值製造變化
_SEQ = [0.6, 1.0, 0.4, 0.85, 0.55, 1.2, 0.3, 0.95, 0.7, 1.1, 0.5, 0.8, 0.65, 1.05, 0.45]


def _daily_tokens(scale: float, day_idx: int, model_idx: int) -> int:
    """產生某天某模型的合併 token 數（確定性）。"""
    base = 1_800_000  # 1.8M tokens/day baseline（cache-heavy 實況）
    factor = _SEQ[(day_idx + model_idx * 3) % len(_SEQ)]
    return int(base * scale * factor)


def _split_tokens(combined: int) -> dict[str, int]:
    """以實況常見比例拆 tier：cache_read 主導。"""
    return {
        "input_tokens": int(combined * 0.04),
        "output_tokens": int(combined * 0.03),
        "cache_creation_input_tokens": int(combined * 0.08),
        "cache_read_input_tokens": int(combined * 0.85),
    }


def generate_report(dev_id: str, machine: str, days: int, month: str) -> DeveloperReport:
    profile = DEV_PROFILE[dev_id]
    daily: list[DailyUsage] = []
    for d in range(1, days + 1):
        date_str = f"{month}-{d:02d}"
        for mi in profile["models"]:
            model = MODELS[mi]
            combined = _daily_tokens(profile["scale"], d, mi)
            tiers = _split_tokens(combined)
            du = DailyUsage(developer_id=dev_id, date=date_str, model=model, **tiers)
            du.cost_usd = pricing.compute_cost(du)
            daily.append(du)

    # dave 刻意加一個未授權模型 + 被封鎖 MCP → 政策違規
    settings = {"mcpServers": ["context7"], "plugins": ["superpowers"], "models": []}
    if dev_id == "dave@team.dev":
        settings["mcpServers"] = ["context7", "chrome-devtools"]  # chrome-devtools 將被 block
    settings["models"] = sorted({du.model for du in daily})

    total = sum(du.cost_usd for du in daily)
    dates = sorted(du.date for du in daily)
    return DeveloperReport(
        developer_id=dev_id,
        machine=machine,
        generated_at=f"{month}-{days:02d}T12:00:00",
        date_start=dates[0],
        date_end=dates[-1],
        daily=daily,
        total_cost_usd=total,
        settings_snapshot=settings,
    )


def generate_reports(out_dir: Path, month: str, days: int = 20) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    from ccgovern.collector.reporter import save_report
    paths = []
    for dev_id, machine in FAKE_DEVS:
        report = generate_report(dev_id, machine, days, month)
        paths.append(save_report(report, out_dir))
    return paths


def main() -> None:
    # 用當月，讓 dashboard 的「本月」過濾抓得到資料
    month = time.strftime("%Y-%m")
    print(f"產生 {len(FAKE_DEVS)} 位假開發者（月份 {month}）…")
    paths = generate_reports(INGEST_DIR, month, days=20)
    for p in paths:
        print(f"  + {p.name}")

    conn = store.connect(DB_FILE)
    devs = ingest.ingest_dir(conn, INGEST_DIR)
    print(f"已匯入 {len(devs)} 位開發者到 {DB_FILE}")

    # 設預算：alice 是 opus 重用戶，給一個會被預估超支的緊上限 → 觸發告警
    store.set_budget(conn, Budget(scope="team", target="", monthly_cap_usd=2000.0))
    store.set_budget(conn, Budget(scope="dev", target="alice@team.dev", monthly_cap_usd=120.0))
    store.set_budget(conn, Budget(scope="dev", target="bob@team.dev", monthly_cap_usd=200.0))
    # 設政策：允許團隊實際使用的模型，但封鎖 chrome-devtools MCP → 只有 dave 違規（乾淨示範）
    store.set_policy(conn, Policy(
        allowed_models=["claude-opus-4-6", "claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
        blocked_mcp=["chrome-devtools"],
    ))
    conn.commit()
    conn.close()
    print("已設定示範預算與政策。執行 `ccgovern` 開啟 dashboard。")


if __name__ == "__main__":
    main()
