"""TUI 共用：ServerFacade（封裝 store/aggregate/budget/policy）與 vim 導航 mixin。"""

from __future__ import annotations

from datetime import date

from textual.binding import Binding
from textual.widgets import DataTable

from ccgovern.models.governance import Budget, Policy
from ccgovern.server import aggregate, budget, policy, store


class ServerFacade:
    """包住 SQLite 連線與純讀分析函式，TUI 只透過它存取資料。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    def team_totals(self, month: str | None = None):
        return aggregate.team_totals(self.conn, month)

    def developer_summaries(self, month: str | None = None):
        return aggregate.developer_summaries(self.conn, month)

    def developer_detail(self, dev: str):
        return aggregate.developer_detail(self.conn, dev)

    def budgets(self):
        return store.get_budgets(self.conn)

    def evaluate_all(self, today: date | None = None):
        return budget.evaluate_all(self.conn, today or date.today())

    def set_budget(self, b: Budget):
        store.set_budget(self.conn, b)

    def policy(self) -> Policy:
        return store.get_policy(self.conn)

    def set_policy(self, p: Policy):
        store.set_policy(self.conn, p)

    def violations(self):
        return policy.check_all(self.conn, self.policy())


VIM_BINDINGS = [
    Binding("j", "cursor_down", "j/k 移動"),
    Binding("k", "cursor_up", "↑", show=False),
    Binding("g", "go_top", "g 頂"),
    Binding("G", "go_bottom", "G 底"),
]


class VimTableMixin:
    """為含單一 DataTable 的 Vertical widget 提供 vim 導航。子類需設 TABLE_ID。"""

    TABLE_ID = "table"

    def _table(self) -> DataTable:
        return self.query_one(f"#{self.TABLE_ID}", DataTable)

    def _move(self, delta: int) -> None:
        t = self._table()
        if t.row_count == 0:
            return
        target = max(0, min(t.row_count - 1, (t.cursor_row or 0) + delta))
        t.move_cursor(row=target)

    def action_cursor_down(self) -> None:
        self._move(1)

    def action_cursor_up(self) -> None:
        self._move(-1)

    def action_go_top(self) -> None:
        self._move(-10**9)

    def action_go_bottom(self) -> None:
        self._move(10**9)
