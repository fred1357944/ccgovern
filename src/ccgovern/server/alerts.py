"""預算/政策告警通知 — Slack incoming webhook + 通用 webhook。純 stdlib。

用法（可排 cron，每天跑一次）：
    ccgovern-alert --slack-webhook https://hooks.slack.com/services/XXX
    ccgovern-alert --dry-run          # 只印出會發什麼，不真的發
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.error
import urllib.request
from datetime import date

from ccgovern.config import DB_FILE
from ccgovern.server import budget, policy, store


def build_alert_lines(conn: sqlite3.Connection, today: date) -> list[str]:
    """彙整需要通知的事項；無事回傳空 list（就不發）。"""
    lines: list[str] = []
    for st in budget.evaluate_all(conn, today):
        target = st.budget.target or "全團隊"
        if st.level == "over":
            lines.append(
                f"🔴 {target} 本月已超支：${st.spent:,.2f} / 上限 ${st.cap:,.0f}"
            )
        elif st.level == "warn":
            lines.append(
                f"🟡 {target} 預估月底超支：已花 ${st.spent:,.2f}，"
                f"預估 ${st.projected:,.2f} / 上限 ${st.cap:,.0f}"
            )
    for v in policy.check_all(conn, store.get_policy(conn)):
        if v.severity == "error":
            lines.append(f"🔴 政策違規：{v.developer_id} — {v.detail}")
    return lines


def send_slack(webhook_url: str, text: str) -> tuple[bool, str]:
    """發到 Slack incoming webhook（也相容多數通用 webhook 接收端）。"""
    body = json.dumps({"text": text}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status < 300, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, OSError) as e:
        return False, str(e)


def main() -> None:
    parser = argparse.ArgumentParser(description="檢查預算/政策並發送告警")
    parser.add_argument("--slack-webhook", default=None, help="Slack incoming webhook URL")
    parser.add_argument("--dry-run", action="store_true", help="只印出，不發送")
    args = parser.parse_args()

    conn = store.connect(DB_FILE)
    try:
        lines = build_alert_lines(conn, date.today())
    finally:
        conn.close()

    if not lines:
        print("✓ 無告警事項")
        return

    text = "*CCGovern 告警*\n" + "\n".join(lines)
    # 未授權浮水印
    from ccgovern.license import trial_banner
    from ccgovern.server import aggregate
    conn2 = store.connect(DB_FILE)
    try:
        dev_count = aggregate.team_totals(conn2)["dev_count"]
    finally:
        conn2.close()
    banner = trial_banner(dev_count)
    if banner:
        text += f"\n_{banner}_"
    print(text)
    if args.dry_run or not args.slack_webhook:
        if not args.slack_webhook and not args.dry_run:
            print("（未指定 --slack-webhook，僅顯示）")
        return
    ok, msg = send_slack(args.slack_webhook, text)
    print(("✓ 已發送 " if ok else "✗ 發送失敗 ") + msg)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
