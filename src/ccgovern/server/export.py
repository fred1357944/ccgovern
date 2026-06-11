"""經理月報匯出 — Markdown / CSV。給不開終端機的買單者（經理/財務）看。"""

from __future__ import annotations

import argparse
import csv
import io
import sqlite3
import time
from datetime import date
from pathlib import Path

from ccgovern.config import DB_FILE
from ccgovern.server import aggregate, budget, policy, store

_LEVEL_LABEL = {"ok": "正常", "warn": "預估超支", "over": "已超支"}


def monthly_markdown(conn: sqlite3.Connection, month: str, today: date) -> str:
    """產出單月團隊成本月報（Markdown）。"""
    totals = aggregate.team_totals(conn, month)
    summaries = aggregate.developer_summaries(conn, month)
    statuses = {st.budget.target: st for st in budget.evaluate_all(conn, today)
                if st.budget.scope == "dev"}
    team_status = next((st for st in budget.evaluate_all(conn, today)
                        if st.budget.scope == "team"), None)
    violations = policy.check_all(conn, store.get_policy(conn))

    lines = [
        f"# AI 編碼工具成本月報 — {month}",
        "",
        f"- 開發者人數：**{totals['dev_count']}**",
        f"- 本月總花費：**${totals['total_cost']:,.2f}**",
        f"- 總 tokens：{totals['total_tokens']:,}",
    ]
    if team_status:
        lines.append(
            f"- 團隊預算：${team_status.cap:,.0f}（已用 {team_status.pct_of_cap*100:.0f}%，"
            f"預估月底 ${team_status.projected:,.2f} → {_LEVEL_LABEL[team_status.level]}）"
        )
    lines += ["", "## 各開發者", "",
              "| 開發者 | 本月花費 | 月預算 | 狀態 | 主要模型 |",
              "|---|---:|---:|---|---|"]
    for s in summaries:
        st = statuses.get(s.developer_id)
        cap = f"${st.cap:,.0f}" if st else "—"
        level = _LEVEL_LABEL[st.level] if st else "—"
        lines.append(
            f"| {s.developer_id} | ${s.month_cost_usd:,.2f} | {cap} | {level} | {s.top_model} |"
        )

    lines += ["", "## 模型花費分佈", "", "| 模型 | 花費 | tokens |", "|---|---:|---:|"]
    for model, v in totals["by_model"].items():
        lines.append(f"| {model} | ${v['cost']:,.2f} | {v['tokens']:,} |")

    lines += ["", "## 政策違規", ""]
    if violations:
        for v in violations:
            mark = "🔴" if v.severity == "error" else "🟡"
            lines.append(f"- {mark} **{v.developer_id}**：{v.detail}")
    else:
        lines.append("（無）")

    lines += ["", "---", f"*由 CCGovern 產生（每日成本為估算；報表日 {today.isoformat()}）*"]
    from ccgovern.license import trial_banner
    banner = trial_banner(totals["dev_count"])
    if banner:
        lines += ["", f"**{banner}**"]
    lines.append("")
    return "\n".join(lines)


def monthly_csv(conn: sqlite3.Connection, month: str) -> str:
    """每開發者 × 模型的月度明細 CSV（餵試算表/BI 用）。"""
    rows = conn.execute(
        """
        SELECT developer_id, model,
               SUM(input_tokens) AS input_tokens,
               SUM(output_tokens) AS output_tokens,
               SUM(cache_creation_input_tokens) AS cache_creation,
               SUM(cache_read_input_tokens) AS cache_read,
               SUM(cost_usd) AS cost_usd
        FROM daily_usage WHERE date LIKE ?
        GROUP BY developer_id, model
        ORDER BY developer_id, cost_usd DESC
        """,
        (f"{month}%",),
    ).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["developer_id", "model", "input_tokens", "output_tokens",
                "cache_creation_tokens", "cache_read_tokens", "cost_usd"])
    for r in rows:
        w.writerow([r["developer_id"], r["model"], r["input_tokens"], r["output_tokens"],
                    r["cache_creation"], r["cache_read"], f"{r['cost_usd']:.4f}"])
    return buf.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="匯出 CCGovern 月報（Markdown + CSV）")
    parser.add_argument("--month", default=None, help="YYYY-MM（預設當月）")
    parser.add_argument("--out", default=".", help="輸出目錄")
    args = parser.parse_args()

    month = args.month or time.strftime("%Y-%m")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = store.connect(DB_FILE)
    try:
        md = monthly_markdown(conn, month, date.today())
        csv_text = monthly_csv(conn, month)
    finally:
        conn.close()

    md_path = out_dir / f"ccgovern-report-{month}.md"
    csv_path = out_dir / f"ccgovern-report-{month}.csv"
    md_path.write_text(md, encoding="utf-8")
    csv_path.write_text(csv_text, encoding="utf-8")
    print(f"已產出：{md_path}")
    print(f"已產出：{csv_path}")


if __name__ == "__main__":
    main()
