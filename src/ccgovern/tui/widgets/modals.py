"""共用 Modal：輸入框與清單挑選。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView, Static


class InputModal(ModalScreen[str | None]):
    """輸入一段文字，回傳字串（None = 取消）。"""

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def __init__(self, title: str, initial: str = "") -> None:
        super().__init__()
        self._title = title
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold]{self._title}[/bold]")
            yield Input(value=self._initial, id="modal-input")

    def on_mount(self) -> None:
        self.query_one("#modal-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)


class PickerModal(ModalScreen[str | None]):
    """從清單挑一項，回傳 value（None = 取消）。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        Binding("j", "down", "下", show=False),
        Binding("k", "up", "上", show=False),
    ]

    def __init__(self, title: str, items: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._items = items

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(f"[bold]{self._title}[/bold]")
            yield Static("[dim]j/k 移動，Enter 選擇，Esc 取消[/dim]")
            yield ListView(
                *[ListItem(Label(lbl), id=f"pick-{i}") for i, (lbl, _) in enumerate(self._items)]
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None or event.item.id is None:
            return
        idx = int(event.item.id.split("-")[1])
        self.dismiss(self._items[idx][1])

    def action_down(self) -> None:
        self.query_one(ListView).action_cursor_down()

    def action_up(self) -> None:
        self.query_one(ListView).action_cursor_up()

    def action_cancel(self) -> None:
        self.dismiss(None)
