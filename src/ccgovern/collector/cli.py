"""ccgovern-collect 入口：跑在每位開發者機器，產出可上傳的 DeveloperReport。"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from ccgovern.collector.reporter import build_report, resolve_developer_id, save_report
from ccgovern.config import INGEST_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description="收集本機 Claude Code 用量，產出 DeveloperReport JSON")
    parser.add_argument("--out", default=str(INGEST_DIR), help="輸出（匯入）目錄")
    parser.add_argument("--developer-id", default=None, help="開發者識別（預設用 git user.email）")
    parser.add_argument("--upload", default=None, metavar="URL",
                        help="直接上傳到 CCGovern sync server（例：http://server:8377）")
    parser.add_argument("--token", default=None, help="上傳用 Bearer token")
    args = parser.parse_args()

    dev = args.developer_id or resolve_developer_id()
    generated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    report = build_report(developer_id=dev, generated_at=generated_at)

    print(f"開發者：{dev}")
    print(f"涵蓋日期：{report.date_start} ~ {report.date_end}")
    print(f"總成本（估算）：${report.total_cost_usd:,.2f}")

    if args.upload:
        ok, msg = upload_report(report, args.upload, args.token)
        print(("✓ " if ok else "✗ ") + msg)
        if not ok:
            raise SystemExit(1)
    else:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = save_report(report, out_dir)
        print(f"已寫入：{path}")


def upload_report(report, base_url: str, token: str | None = None) -> tuple[bool, str]:
    """POST 報告到 sync server。純 stdlib（urllib），零依賴。"""
    import json
    import urllib.error
    import urllib.request

    url = base_url.rstrip("/") + "/v1/reports"
    body = json.dumps(report.to_dict(), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, f"已上傳到 {url}（{data.get('daily_rows', '?')} 筆）"
    except urllib.error.HTTPError as e:
        return False, f"上傳失敗 HTTP {e.code}：{e.read().decode('utf-8', 'replace')[:200]}"
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return False, f"上傳失敗：{e}"


if __name__ == "__main__":
    main()
