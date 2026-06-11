"""v0.2 測試：HTTP 上傳 roundtrip、token 驗證、月報匯出。"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import pytest

from ccgovern.models.governance import Budget, Policy
from ccgovern.models.report import DeveloperReport
from ccgovern.models.usage import DailyUsage
from ccgovern.server import aggregate, export, http_sync, ingest, store


def _report(dev: str = "carol@x", cost: float = 12.5) -> DeveloperReport:
    return DeveloperReport(
        developer_id=dev, machine="m1", generated_at="2026-06-10T00:00:00",
        date_start="2026-06-01", date_end="2026-06-01",
        daily=[DailyUsage(dev, "2026-06-01", "claude-opus-4-6", input_tokens=100, cost_usd=cost)],
        total_cost_usd=cost,
        settings_snapshot={"mcpServers": [], "plugins": []},
    )


@pytest.fixture()
def server(tmp_path: Path):
    """啟動一個隨機埠的 sync server（帶 token），測後關閉。"""
    srv = http_sync.make_server(
        host="127.0.0.1", port=0,
        ingest_dir=tmp_path / "ingest", db_path=tmp_path / "db.sqlite",
        token="secret123",
    )
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, tmp_path
    srv.shutdown()


def _post(url: str, obj: dict, token: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        url, data=json.dumps(obj).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_http_upload_roundtrip(server):
    srv, tmp_path = server
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"

    # health 不需 token
    with urllib.request.urlopen(f"{base}/v1/health", timeout=10) as resp:
        assert json.loads(resp.read())["status"] == "ok"

    # 上傳一份報告
    code, data = _post(f"{base}/v1/reports", _report().to_dict(), token="secret123")
    assert code == 200
    assert data["developer_id"] == "carol@x"
    assert data["daily_rows"] == 1

    # 落地檔案 + 已入 DB
    assert list((tmp_path / "ingest").glob("*.json"))
    conn = store.connect(tmp_path / "db.sqlite")
    totals = aggregate.team_totals(conn, "2026-06")
    assert totals["dev_count"] == 1
    assert totals["total_cost"] == pytest.approx(12.5)
    conn.close()


def test_http_rejects_bad_token_and_bad_body(server):
    srv, _ = server
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"

    code, _ = _post(f"{base}/v1/reports", _report().to_dict(), token="wrong")
    assert code == 401
    code, _ = _post(f"{base}/v1/reports", _report().to_dict(), token=None)
    assert code == 401
    code, _ = _post(f"{base}/v1/reports", {"not": "a report"}, token="secret123")
    assert code == 400


def test_http_rejects_path_traversal_developer_id(server):
    srv, tmp_path = server
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/v1/reports"
    evil = _report(dev="../../etc/pwned").to_dict()
    code, _ = _post(url, evil, token="secret123")
    assert code == 400  # 惡意 developer_id 被擋
    # 確認沒寫出任何檔到 ingest 目錄外
    assert not (tmp_path.parent / "etc").exists()


def test_safe_developer_filename_strips_traversal():
    from ccgovern.collector.reporter import safe_developer_filename
    assert "/" not in safe_developer_filename("../../etc/passwd")
    assert "/" not in safe_developer_filename("a/b/c")
    assert safe_developer_filename("....//") not in ("..", ".", "")
    assert safe_developer_filename("alice@team.dev") == "alice_at_team.dev"


def test_save_report_blocks_path_escape(tmp_path: Path):
    from ccgovern.collector.reporter import save_report
    rep = _report(dev="ok@x")
    p = save_report(rep, tmp_path)
    assert p.parent == tmp_path.resolve()  # 落在 out_dir 內


def test_make_server_refuses_public_bind_without_token(tmp_path: Path):
    import pytest as _pytest
    with _pytest.raises(ValueError, match="拒絕啟動"):
        http_sync.make_server(host="0.0.0.0", port=0,
                              ingest_dir=tmp_path / "i", db_path=tmp_path / "d.sqlite",
                              token=None)
    # loopback 無 token 可以
    srv = http_sync.make_server(host="127.0.0.1", port=0,
                                ingest_dir=tmp_path / "i", db_path=tmp_path / "d.sqlite",
                                token=None)
    srv.server_close()


def test_http_upload_idempotent(server):
    srv, tmp_path = server
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/v1/reports"
    _post(url, _report(cost=5.0).to_dict(), token="secret123")
    _post(url, _report(cost=5.0).to_dict(), token="secret123")  # 重傳
    conn = store.connect(tmp_path / "db.sqlite")
    assert aggregate.team_totals(conn, "2026-06")["total_cost"] == pytest.approx(5.0)
    conn.close()


# ---- 月報匯出 ----

def test_monthly_markdown_and_csv(tmp_path: Path):
    conn = store.connect(tmp_path / "db.sqlite")
    ingest.ingest_report(conn, _report("a@x", 30.0))
    ingest.ingest_report(conn, _report("b@x", 10.0))
    store.set_budget(conn, Budget(scope="team", target="", monthly_cap_usd=100.0))
    store.set_budget(conn, Budget(scope="dev", target="a@x", monthly_cap_usd=20.0))  # 已超支
    store.set_policy(conn, Policy(blocked_mcp=["evil-mcp"]))

    md = export.monthly_markdown(conn, "2026-06", date(2026, 6, 15))
    assert "a@x" in md and "b@x" in md
    assert "$40.00" in md            # 團隊總額
    assert "已超支" in md             # a@x 花 30 > 上限 20
    assert "claude-opus-4-6" in md

    csv_text = export.monthly_csv(conn, "2026-06")
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("developer_id,model")
    assert len(lines) == 3           # header + 2 devs
    assert "30.0000" in csv_text
    conn.close()
