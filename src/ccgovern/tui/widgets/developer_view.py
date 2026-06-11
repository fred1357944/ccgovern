"""開發者明細分頁：選一位開發者，看每日趨勢（估算）+ 模型花費分佈。"""

from __future__ import annotations

import humanize
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from ccgovern.tui.widgets.base import VIM_BINDINGS, ServerFacade, VimTableMixin
from ccgovern.tui.widgets.modals import PickerModal


def _bar(value: float, peak: float, width: int = 28) -> str:
    if peak <= 0:
        return ""
    n = int(round(value / peak * width))
    return "█" * n


class DeveloperView(VimTableMixin, Vertical):
    TABLE_ID = "dev-table"
    BINDINGS = [
        *VIM_BINDINGS,
        Binding("s", "select_dev", "s 選開發者"),
    ]

    def __init__(self, facade: ServerFacade) -> None:
        super().__init__()
        self.facade = facade
        self.current_dev: str | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="dev-summary")
        table = DataTable(id="dev-table", cursor_type="row", zebra_stripes=True)
        table.add_column("模型", key="model")
        table.add_column("花費", width=12, key="cost")
        table.add_column("tokens", width=12, key="tokens")
        table.add_column("占比", width=8, key="pct")
        yield table
        yield Static("", id="trend")
        yield Static("[dim]s 選擇開發者 · j/k 移動 · 趨勢為估算（依 all-time tier 比例拆分）[/dim]", classes="hint")

    def on_mount(self) -> None:
        summaries = self.facade.developer_summaries()
        if summaries:
            self.current_dev = summaries[0].developer_id
        self.refresh_data()

    def refresh_data(self) -> None:
        summary = self.query_one("#dev-summary", Static)
        trend = self.query_one("#trend", Static)
        table = self.query_one("#dev-table", DataTable)
        table.clear()

        if not self.current_dev:
            summary.update("[dim]沒有開發者資料，先執行 ccgovern-demo 或 ccgovern-collect[/dim]")
            trend.update("")
            return

        detail = self.facade.developer_detail(self.current_dev)
        by_model = detail["by_model"]
        total = sum(v["cost"] for v in by_model.values()) or 1.0
        summary.update(
            f"[bold #58a6ff]{self.current_dev}[/bold #58a6ff]   "
            f"總花費 [#d29922]${total:,.2f}[/#d29922]   （按 s 切換開發者）"
        )
        for model, v in by_model.items():
            table.add_row(
                model,
                f"${v['cost']:,.2f}",
                humanize.intword(v["tokens"]),
                f"{v['cost']/total*100:.0f}%",
            )

        # 每日趨勢 bar（文字繪製）
        daily = detail["daily_trend"]
        if daily:
            peak = max(c for _, c in daily) or 1.0
            lines = ["[bold]每日花費趨勢（估算）[/bold]"]
            for d, c in daily[-12:]:
                lines.append(f"[dim]{d}[/dim] [#58a6ff]{_bar(c, peak)}[/#58a6ff] ${c:,.1f}")
            trend.update("\n".join(lines))
        else:
            trend.update("[dim]無每日資料[/dim]")

    def action_select_dev(self) -> None:
        items = [(s.developer_id, s.developer_id) for s in self.facade.developer_summaries()]
        if not items:
            self.app.notify("沒有開發者", severity="warning")
            return

        def _set(dev: str | None) -> None:
            if dev:
                self.current_dev = dev
                self.refresh_data()

        self.app.push_screen(PickerModal("選擇開發者", items), _set)
