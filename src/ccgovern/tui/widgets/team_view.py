"""團隊總覽分頁。"""

from __future__ import annotations

import time
from datetime import date

import humanize
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from ccgovern.tui.widgets.base import VIM_BINDINGS, ServerFacade, VimTableMixin


class TeamView(VimTableMixin, Vertical):
    TABLE_ID = "team-table"
    BINDINGS = [*VIM_BINDINGS]

    def __init__(self, facade: ServerFacade) -> None:
        super().__init__()
        self.facade = facade
        self.month = time.strftime("%Y-%m")

    def compose(self) -> ComposeResult:
        yield Static("", id="summary")
        table = DataTable(id="team-table", cursor_type="row", zebra_stripes=True)
        table.add_column("狀態", width=4, key="status")
        table.add_column("開發者", key="dev")
        table.add_column("機器", width=12, key="machine")
        table.add_column("本月花費", width=12, key="month")
        table.add_column("月預算", width=12, key="budget")
        table.add_column("主要模型", width=22, key="model")
        table.add_column("最後活躍", width=12, key="active")
        yield table
        yield Static("[dim]j/k 移動 · g/G 頂底 · 3 切到預算分頁設定上限 · R 重新匯入[/dim]", classes="hint")

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        # 預算狀態查表
        statuses = {}
        for st in self.facade.evaluate_all(date.today()):
            if st.budget.scope == "dev":
                statuses[st.budget.target] = st

        totals = self.facade.team_totals(self.month)
        summary = self.query_one("#summary", Static)
        text = (
            f"[bold #58a6ff]團隊本月（{self.month}）[/bold #58a6ff]   "
            f"[#3fb950]{totals['dev_count']}[/#3fb950] 人   "
            f"[#d29922]${totals['total_cost']:,.2f}[/#d29922]   "
            f"{humanize.intword(totals['total_tokens'])} tokens"
        )
        from ccgovern.license import trial_banner
        banner = trial_banner(totals["dev_count"])
        if banner:
            text += f"\n[#f85149]{banner}[/#f85149]"
        summary.update(text)

        table = self.query_one("#team-table", DataTable)
        cursor = table.cursor_row
        table.clear()
        for s in self.facade.developer_summaries(self.month):
            st = statuses.get(s.developer_id)
            glyph = "[#3fb950]✓[/#3fb950]"
            cap = "[dim]—[/dim]"
            if st:
                cap = f"${st.cap:,.0f}"
                glyph = {
                    "ok": "[#3fb950]✓[/#3fb950]",
                    "warn": "[#d29922]●[/#d29922]",
                    "over": "[#f85149]✗[/#f85149]",
                }[st.level]
            table.add_row(
                glyph,
                s.developer_id,
                f"[dim]{s.machine}[/dim]",
                f"${s.month_cost_usd:,.2f}",
                cap,
                s.top_model,
                f"[dim]{s.last_active}[/dim]",
            )
        if table.row_count:
            table.move_cursor(row=min(cursor or 0, table.row_count - 1))
