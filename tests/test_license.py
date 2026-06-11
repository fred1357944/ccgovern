"""授權 key 測試（Ed25519 公鑰驗證）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ccgovern import license as lic
from ccgovern.util import ed25519

# 每個 test session 用的臨時賣方金鑰對（不碰真正的內嵌公鑰）
_TEST_SEED, _TEST_PUB = ed25519.generate_keypair(seed=bytes(range(32)))
_TEST_PUB_HEX = _TEST_PUB.hex()


def _key(tier="founding", seats=10) -> str:
    return lic.generate_key(
        tier, seats, "Acme Inc", "2026-06-11", "2028-06-11",
        private_seed=_TEST_SEED,
    )


def _verify(key: str):
    return lic.verify_key(key, public_key_hex=_TEST_PUB_HEX)


# --- Ed25519 模組正確性：RFC 8032 §7.1 TEST 1（空訊息測試向量）---

def test_ed25519_rfc8032_test_vector():
    seed = bytes.fromhex(
        "9d61b19deffd5a60ba844af492ec2cc4"
        "4449c5697b326919703bac031cae7f60"
    )
    expected_pub = "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    expected_sig = (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e0652249015"
        "55fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    s, pub = ed25519.generate_keypair(seed=seed)
    assert pub.hex() == expected_pub
    sig = ed25519.sign(seed, b"")
    assert sig.hex() == expected_sig
    assert ed25519.verify(pub, b"", sig) is True
    # 改訊息 → 驗證失敗
    assert ed25519.verify(pub, b"tampered", sig) is False


# --- 授權 key 行為 ---

def test_generate_and_verify_roundtrip():
    info = _verify(_key())
    assert info is not None
    assert info.tier == "founding"
    assert info.seats == 10
    assert info.licensee == "Acme Inc"


def test_tampered_key_rejected():
    key = _key()
    # 改 payload（席位灌水）→ 簽章不符
    prefix, b64, sig = key.split(".")
    tampered = f"{prefix}.{b64[:-2]}XX.{sig}"
    assert _verify(tampered) is None
    assert _verify("CCGV2.garbage.deadbeef") is None
    assert _verify("not-a-key") is None


def test_key_from_different_keypair_rejected():
    """用 A 私鑰簽，拿內嵌（不同）公鑰驗 → 必須被拒。"""
    other_seed, _ = ed25519.generate_keypair(seed=bytes([0xAA] * 32))
    key = lic.generate_key(
        "team", 25, "Imposter", "2026-06-11", "2028-06-11",
        private_seed=other_seed,
    )
    # 用內嵌公鑰（預設）驗 → 拒
    assert lic.verify_key(key) is None
    # 用測試公鑰（也不同）驗 → 拒
    assert _verify(key) is None


def test_mint_without_private_key_fails_cleanly(monkeypatch, tmp_path):
    """無 env、無 key-file、預設檔不存在 → 清楚的 RuntimeError。"""
    monkeypatch.delenv("CCGOVERN_VENDOR_KEY", raising=False)
    missing = tmp_path / "vendor-private.key"
    monkeypatch.setattr(lic, "VENDOR_KEY_FILE", missing)
    with pytest.raises(RuntimeError, match="找不到賣方私鑰"):
        lic.generate_key("founding", 10, "Acme", "2026-06-11", "2028-06-11")


def test_save_and_load_license(tmp_path: Path, monkeypatch):
    # save/load 走內嵌公鑰路徑 → 用測試公鑰 monkeypatch 內嵌常數
    monkeypatch.setattr(lic, "PUBLIC_KEY_HEX", _TEST_PUB_HEX)
    path = tmp_path / "license.key"
    ok, msg = lic.save_license(_key(), path)
    assert ok
    loaded = lic.load_license(path)
    assert loaded and loaded.licensee == "Acme Inc"
    ok, _ = lic.save_license("bogus", path)
    assert not ok


def test_trial_banner_logic(tmp_path: Path):
    nolic = tmp_path / "none.key"
    # 未授權 + 3 人以內 → 無浮水印
    assert lic.trial_banner(3, path=nolic) is None
    # 未授權 + 超過免費上限 → 浮水印
    assert "未授權" in lic.trial_banner(5, path=nolic)
    # 已授權 + 席位內 → 無
    info = _verify(_key(seats=10))
    assert lic.trial_banner(8, lic=info) is None
    # 已授權 + 超席位 → 升級提示
    assert "超出授權席位" in lic.trial_banner(12, lic=info)
    # 企業版無上限
    ent = _verify(_key(tier="enterprise", seats=0))
    assert lic.trial_banner(500, lic=ent) is None
