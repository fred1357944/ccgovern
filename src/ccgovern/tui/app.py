"""CCGovern 主程式。"""

from __future__ import annotations

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from ccgovern.config import DB_FILE, INGEST_DIR, Settings
from ccgovern.server import ingest, store
from ccgovern.tui.widgets.base import ServerFacade
from ccgovern.tui.widgets.budget_view import BudgetView
from ccgovern.tui.widgets.developer_view import DeveloperView
from ccgovern.tui.widgets.policy_view import PolicyView
from ccgovern.tui.widgets.team_view import TeamView


class CCGovernApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "CCGovern"
    SUB_TITLE = "團隊 AI 成本治理"

    BINDINGS = [
        Binding("q", "quit", "離開"),
        Binding("1", "show_tab('team')", "團隊", show=False),
        Binding("2", "show_tab('dev')", "開發者", show=False),
        Binding("3", "show_tab('budget')", "預算", show=False),
        Binding("4", "show_tab('policy')", "政策", show=False),
        Binding("R", "reingest", "R 重新匯入"),
        Binding("?", "help", "說明"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings.load()
        self.conn = store.connect(DB_FILE, same_thread=False)
        self.facade = ServerFacade(self.conn)
        self._gen = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs"):
            with TabPane("團隊總覽 (1)", id="team"):
                yield TeamView(self.facade)
            with TabPane("開發者明細 (2)", id="dev"):
                yield DeveloperView(self.facade)
            with TabPane("預算/告警 (3)", id="budget"):
                yield BudgetView(self.facade)
            with TabPane("政策 (4)", id="policy"):
                yield PolicyView(self.facade)
        yield Footer()

    def on_mount(self) -> None:
        # cache-first：DB 已有資料就直接顯示（compose 已渲染），背景再重新匯入
        self._reingest_worker()

    @work(thread=True, exclusive=True)
    def _reingest_worker(self) -> None:
        self._gen += 1
        gen = self._gen
        devs = ingest.ingest_dir(self.conn, INGEST_DIR)
        if gen != self._gen:
            return
        self.app.call_from_thread(self._refresh_all)
        self.app.call_from_thread(
            self.app.notify, f"已匯入 {len(devs)} 位開發者" if devs else "ingest 目錄無新資料"
        )

    def _refresh_all(self) -> None:
        for view_cls in (TeamView, DeveloperView, BudgetView, PolicyView):
            for w in self.query(view_cls):
                w.refresh_data()

    def action_show_tab(self, tab: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab

    def action_reingest(self) -> None:
        self.notify("重新匯入中…")
        self._reingest_worker()

    def action_help(self) -> None:
        self.notify(
            "1-4 切分頁 · j/k 移動 · g/G 頂底 · R 重新匯入\n"
            "團隊：看每人本月花費 vs 預算 · 開發者：s 選人看明細\n"
            "預算：b 設上限 · 政策：e 編輯清單",
            timeout=8,
        )

    def on_unmount(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


def main() -> None:
    CCGovernApp().run()


if __name__ == "__main__":
    main()
