"""半自動出貨 — 你收到付款通知後，一行指令簽 key + 產買家 email 草稿。

設計：私鑰只在你本機，金流（LS/Stripe/Wise…）無關。流程：
  ccgovern-fulfill --email buyer@corp.com --order LS-1234
→ 簽 founding key、記錄訂單（防重複/漏簽）、印出可直接寄的 email 草稿。

訂單記錄存 ~/.config/ccgovern/orders.json（本機，含買家 email，勿外洩）。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from ccgovern.config import CONFIG_DIR
from ccgovern.license import TIERS, generate_key
from ccgovern.util.atomic_io import atomic_write_json

ORDERS_FILE = CONFIG_DIR / "orders.json"


@dataclass
class Order:
    order_id: str
    email: str
    tier: str
    seats: int
    issued: str
    updates_until: str
    key: str


def load_orders(path: Path = ORDERS_FILE) -> dict[str, Order]:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {k: Order(**v) for k, v in raw.items()}


def save_orders(orders: dict[str, Order], path: Path = ORDERS_FILE) -> None:
    atomic_write_json(path, {k: asdict(v) for k, v in orders.items()}, backup=True)


def fulfill(
    email: str,
    order_id: str,
    tier: str = "founding",
    seats: int | None = None,
    updates_years: int = 2,
    today: date | None = None,
    private_seed: bytes | None = None,
    orders_path: Path = ORDERS_FILE,
) -> tuple[Order, bool]:
    """簽發 key 並記錄訂單。回傳 (Order, 是否為既有訂單)。

    today 由呼叫端注入（避免在此取系統時間，方便測試）。
    既有 order_id 直接回傳原 key（idempotent，避免重複簽發/重複收費烏龍）。
    """
    orders = load_orders(orders_path)
    if order_id in orders:
        return orders[order_id], True

    if tier not in TIERS:
        raise ValueError(f"未知方案：{tier}")
    if seats is None:
        seats = TIERS[tier]["max_seats"] or 0

    today = today or date.today()
    issued = today.isoformat()
    updates_until = today.replace(year=today.year + updates_years).isoformat()
    key = generate_key(tier, seats, email, issued, updates_until, private_seed=private_seed)

    order = Order(order_id, email, tier, seats, issued, updates_until, key)
    orders[order_id] = order
    save_orders(orders, orders_path)
    return order, False


def email_draft(order: Order) -> str:
    """產生可直接寄給買家的 email 草稿（英文，B2B 買家多為 US/EU）。"""
    seat_label = "unlimited" if order.seats == 0 else f"{order.seats}"
    tier_label = TIERS.get(order.tier, {}).get("label", order.tier)
    return f"""Subject: Your CCGovern license key (order {order.order_id})

Hi,

Thank you for purchasing CCGovern — {tier_label}. Here's your license key:

    {order.key}

To activate (offline, runs on your own network):

    ccgovern-license activate "{order.key}"

This license covers {seat_label} developer seats, with updates through
{order.updates_until}. The software itself is yours permanently.

Get started:
  1. git clone https://github.com/fred1357944/ccgovern
  2. uv venv .venv && source .venv/bin/activate && uv pip install -e .
  3. ccgovern-license activate "<key above>"
  4. Run a collector on each dev machine, point them at your server, open `ccgovern`.

As a founding user, all future features (including the upcoming Cursor /
Copilot collectors) are included at no extra cost, forever.

Any questions — just reply to this email.

— laihongyi
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="CCGovern 半自動出貨：簽 key + 產 email 草稿")
    parser.add_argument("--email", required=True, help="買家 email（會寫進授權 licensee）")
    parser.add_argument("--order", required=True, help="訂單編號（金流平台的，用來防重複簽發）")
    parser.add_argument("--tier", default="founding", choices=list(TIERS))
    parser.add_argument("--seats", type=int, default=None, help="席位（省略用方案預設）")
    parser.add_argument("--updates-years", type=int, default=2)
    args = parser.parse_args()

    order, existed = fulfill(
        email=args.email, order_id=args.order, tier=args.tier,
        seats=args.seats, updates_years=args.updates_years,
    )
    if existed:
        print(f"⚠ 訂單 {args.order} 已出貨過，回傳原 key（未重複簽發）")
    else:
        print(f"✓ 已簽發並記錄訂單 {args.order}")
    print("=" * 60)
    print(email_draft(order))


if __name__ == "__main__":
    main()
