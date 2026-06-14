"""半自動出貨測試。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ccgovern import fulfillment as f
from ccgovern.license import verify_key
from ccgovern.util import ed25519

_SEED, _PUB = ed25519.generate_keypair(seed=bytes(range(32)))


def test_fulfill_signs_and_records(tmp_path: Path):
    orders = tmp_path / "orders.json"
    order, existed = f.fulfill(
        email="buyer@corp.com", order_id="LS-1", today=date(2026, 6, 14),
        private_seed=_SEED, orders_path=orders,
    )
    assert not existed
    assert order.tier == "founding"
    assert order.seats == 10            # 方案預設
    assert order.updates_until == "2028-06-14"  # +2 年
    info = verify_key(order.key, public_key_hex=_PUB.hex())
    assert info and info.licensee == "buyer@corp.com"


def test_fulfill_idempotent_same_order(tmp_path: Path):
    orders = tmp_path / "orders.json"
    o1, _ = f.fulfill("a@x", "LS-9", today=date(2026, 6, 14), private_seed=_SEED, orders_path=orders)
    o2, existed = f.fulfill("a@x", "LS-9", today=date(2026, 6, 14), private_seed=_SEED, orders_path=orders)
    assert existed                      # 同訂單不重簽
    assert o1.key == o2.key             # 回傳原 key


def test_email_draft_contains_key_and_activate(tmp_path: Path):
    order, _ = f.fulfill("buyer@corp.com", "LS-2", today=date(2026, 6, 14),
                         private_seed=_SEED, orders_path=tmp_path / "o.json")
    draft = f.email_draft(order)
    assert order.key in draft
    assert "ccgovern-license activate" in draft
    assert "10 developer seats" in draft


def test_enterprise_unlimited_seats(tmp_path: Path):
    order, _ = f.fulfill("ent@corp.com", "LS-3", tier="enterprise",
                         today=date(2026, 6, 14), private_seed=_SEED, orders_path=tmp_path / "o.json")
    assert order.seats == 0
    assert "unlimited" in f.email_draft(order)
