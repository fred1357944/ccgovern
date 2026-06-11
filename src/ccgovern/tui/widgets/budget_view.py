"""預算/告警分頁：團隊與個人月預算、預估月底、超支告警。"""

from __future__ import annotations

from datetime import date

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from ccgovern.models.governance import Budget
from ccgovern.tui.widgets.base import VIM_BINDINGS, ServerFacade, VimTableMixin
from ccgovern.tui.widgets.modals import InputModal

_LEVEL = {
    "ok": "[#3fb950]正常[/#3fb950]",
    "warn": "[#d29922]預估超支[/#d29922]",
    "over": "[#f85149]已超支[/#f85149]",
}


class BudgetView(VimTableMixin, Vertical):
    TABLE_ID = "budget-table"
    BINDINGS = [
        *VIM_BINDINGS,
        Binding("b", "set_cap", "b 設上限"),
    ]

    def __init__(self, facade: ServerFacade) -> None:
        super().__init__()
        self.facade = facade
        self._statuses = []

    def compose(self) -> ComposeResult:
        yield Static("", id="budget-summary")
        table = DataTable(id="budget-table", cursor_type="row", zebra_stripes=True)
        table.add_column("範圍", width=8, key="scope")
        table.add_column("對象", key="target")
        table.add_column("月上限", width=12, key="cap")
        table.add_column("本月實際", width=12, key="spent")
        table.add_column("預估月底", width=12, key="proj")
        table.add_column("狀態", width=12, key="status")
        yield table
        yield Static("[dim]b 設定選取項目的月上限 · j/k 移動[/dim]", classes="hint")

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        self._statuses = self.facade.evaluate_all(date.today())
        alerts = sum(1 for s in self._statuses if s.alert)
        self.query_one("#budget-summary", Static).update(
            f"[bold #58a6ff]預算告警[/bold #58a6ff]   "
            f"共 {len(self._statuses)} 條預算   "
            + (f"[#f85149]{alerts} 條告警[/#f85149]" if alerts else "[#3fb950]全部正常[/#3fb950]")
        )
        table = self.query_one("#budget-table", DataTable)
        cursor = table.cursor_row
        table.clear()
        for st in self._statuses:
            scope = "團隊" if st.budget.scope == "team" else "個人"
            target = st.budget.target or "（全團隊）"
            table.add_row(
                scope, target,
                f"${st.cap:,.0f}",
                f"${st.spent:,.2f}",
                f"${st.projected:,.2f}",
                _LEVEL[st.level],
            )
        if table.row_count:
            table.move_cursor(row=min(cursor or 0, table.row_count - 1))

    def action_set_cap(self) -> None:
        table = self.query_one("#budget-table", DataTable)
        if not self._statuses or table.cursor_row is None:
            return
        st = self._statuses[table.cursor_row]
        b = st.budget

        def _save(val: str | None) -> None:
            if val is None:
                return
            try:
                cap = float(val)
            except ValueError:
                self.app.notify("請輸入數字", severity="warning")
                return
            self.facade.set_budget(Budget(scope=b.scope, target=b.target, monthly_cap_usd=cap))
            self.refresh_data()
            self.app.notify(f"已更新上限為 ${cap:,.0f}")

        self.app.push_screen(InputModal(f"設定 {b.target or '團隊'} 月上限（USD）", str(b.monthly_cap_usd)), _save)
