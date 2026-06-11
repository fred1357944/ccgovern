"""HTTP 上傳端點 — 讓多台開發者機器直接 POST 報告到中央，不再靠共享資料夾。

純 stdlib（http.server），零新依賴。MVP 等級的簡單 token 驗證：
啟動時指定 --token，上傳端帶 Authorization: Bearer <token>。

POST /v1/reports   body = DeveloperReport JSON → 寫入 ingest 目錄（atomic）並匯入 DB
GET  /v1/health    → {"status": "ok"}
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ccgovern.config import DB_FILE, INGEST_DIR
from ccgovern.models.report import DeveloperReport
from ccgovern.server import ingest, store

MAX_BODY = 50 * 1024 * 1024  # 50MB 上限，防誤傳大檔


class SyncHandler(BaseHTTPRequestHandler):
    # 由 make_server 注入
    ingest_dir: Path = INGEST_DIR
    db_path: Path = DB_FILE
    token: str | None = None
    _db_lock = threading.Lock()

    def log_message(self, fmt: str, *args) -> None:  # 安靜模式，避免洗 stderr
        pass

    def _send_json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if not self.token:
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {self.token}"

    def do_GET(self) -> None:
        if self.path == "/v1/health":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/v1/reports":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._send_json(400, {"error": "invalid content length"})
            return
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send_json(400, {"error": "invalid json"})
            return
        if not isinstance(data, dict) or not data.get("developer_id"):
            self._send_json(400, {"error": "missing developer_id"})
            return

        report = DeveloperReport.from_dict(data)
        # 1) 落地到 ingest 目錄（留存原始報告，與檔案流程一致）
        from ccgovern.collector.reporter import save_report
        save_report(report, self.ingest_dir)
        # 2) 直接匯入 DB（單一 lock 序列化寫入）
        with self._db_lock:
            conn = store.connect(self.db_path)
            try:
                ingest.ingest_report(conn, report)
            finally:
                conn.close()
        self._send_json(200, {
            "status": "ok",
            "developer_id": report.developer_id,
            "daily_rows": len(report.daily),
        })


def make_server(
    host: str = "127.0.0.1",
    port: int = 8377,
    ingest_dir: Path = INGEST_DIR,
    db_path: Path = DB_FILE,
    token: str | None = None,
) -> ThreadingHTTPServer:
    """建立（未啟動的）伺服器；測試可用 port=0 取隨機埠。"""
    handler = type("BoundSyncHandler", (SyncHandler,), {
        "ingest_dir": Path(ingest_dir),
        "db_path": Path(db_path),
        "token": token,
    })
    Path(ingest_dir).mkdir(parents=True, exist_ok=True)
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="CCGovern 報告上傳伺服器")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8377)
    parser.add_argument("--token", default=None, help="Bearer token（建議設定）")
    args = parser.parse_args()

    server = make_server(args.host, args.port, token=args.token)
    print(f"CCGovern sync server 監聽 {args.host}:{args.port}")
    print(f"上傳端點：POST /v1/reports（{'需要 token' if args.token else '⚠ 未設 token，僅限信任網路'}）")
    print(f"資料落地：{INGEST_DIR} → {DB_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n關閉中…")
        server.shutdown()


if __name__ == "__main__":
    main()
