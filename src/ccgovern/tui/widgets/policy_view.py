"""政策分頁：允許的 model/MCP/plugin 清單 + 違規列表。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from ccgovern.models.governance import Policy
from ccgovern.tui.widgets.base import VIM_BINDINGS, ServerFacade, VimTableMixin
from ccgovern.tui.widgets.modals import InputModal

_FIELDS = [
    ("allowed_models", "允許模型"),
    ("allowed_mcp", "允許 MCP"),
    ("blocked_mcp", "封鎖 MCP"),
    ("allowed_plugins", "允許 plugin"),
]


class PolicyView(VimTableMixin, Vertical):
    TABLE_ID = "policy-table"
    BINDINGS = [
        *VIM_BINDINGS,
        Binding("e", "edit_field", "e 編輯清單"),
    ]

    def __init__(self, facade: ServerFacade) -> None:
        super().__init__()
        self.facade = facade

    def compose(self) -> ComposeResult:
        yield Static("", id="policy-summary")
        table = DataTable(id="policy-table", cursor_type="row", zebra_stripes=True)
        table.add_column("政策項目", width=14, key="field")
        table.add_column("清單（逗號分隔，空=全允許）", key="value")
        yield table
        yield Static("", id="policy-list")
        yield Static("[dim]e 編輯選取的政策清單 · j/k 移動 · 空清單代表不限制[/dim]", classes="hint")

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        pol = self.facade.policy()
        table = self.query_one("#policy-table", DataTable)
        cursor = table.cursor_row
        table.clear()
        for attr, label in _FIELDS:
            vals = getattr(pol, attr)
            table.add_row(label, ", ".join(vals) if vals else "[dim]（全允許）[/dim]")
        if table.row_count:
            table.move_cursor(row=min(cursor or 0, table.row_count - 1))

        violations = self.facade.violations()
        self.query_one("#policy-summary", Static).update(
            f"[bold #58a6ff]政策[/bold #58a6ff]   "
            + (f"[#f85149]{len(violations)} 項違規[/#f85149]" if violations else "[#3fb950]無違規[/#3fb950]")
        )
        listing = self.query_one("#policy-list", Static)
        if violations:
            lines = ["[bold]違規列表[/bold]"]
            for v in violations:
                color = "#f85149" if v.severity == "error" else "#d29922"
                lines.append(f"[{color}]●[/{color}] {v.developer_id}：{v.detail}")
            listing.update("\n".join(lines))
        else:
            listing.update("[dim]目前所有開發者皆符合政策[/dim]")

    def action_edit_field(self) -> None:
        table = self.query_one("#policy-table", DataTable)
        if table.cursor_row is None:
            return
        attr, label = _FIELDS[table.cursor_row]
        pol = self.facade.policy()
        current = ", ".join(getattr(pol, attr))

        def _save(val: str | None) -> None:
            if val is None:
                return
            items = [x.strip() for x in val.split(",") if x.strip()]
            new_pol = Policy(
                allowed_models=pol.allowed_models,
                allowed_mcp=pol.allowed_mcp,
                blocked_mcp=pol.blocked_mcp,
                allowed_plugins=pol.allowed_plugins,
            )
            setattr(new_pol, attr, items)
            self.facade.set_policy(new_pol)
            self.refresh_data()
            self.app.notify(f"已更新「{label}」")

        self.app.push_screen(InputModal(f"編輯「{label}」（逗號分隔）", current), _save)
