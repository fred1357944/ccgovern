"""授權 key — 離線驗證（買斷制：客戶內網無外連，必須本地可驗）。

Key 格式：CCGV2.<base64url(payload-json)>.<base64url(64-byte Ed25519 簽章)>
payload = {tier, seats, licensee, issued, updates_until}

防護等級：**真公鑰驗證（Ed25519，RFC 8032）**。簽發用賣方私鑰種子，驗證只用
公鑰（PUBLIC_KEY_HEX，內嵌於本模組）。因此本 repo 可放心開源——光有源碼
（只含公鑰）無法偽造授權 key。**私鑰種子（vendor-private.key）必須保密並備份**，
一旦外洩或遺失，前者導致可被偽造、後者導致無法再簽發（需換新公鑰）。

純 Python Ed25519 實作見 ccgovern/util/ed25519.py，零新增 runtime 相依。

試用政策：未授權不擋任何功能；超過 FREE_DEV_LIMIT 位開發者時，
dashboard / 月報 / 告警會帶「未授權」浮水印。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path

from ccgovern.config import CONFIG_DIR
from ccgovern.util import ed25519

LICENSE_FILE = CONFIG_DIR / "license.key"
VENDOR_KEY_FILE = CONFIG_DIR / "vendor-private.key"
FREE_DEV_LIMIT = 3

# 賣方公鑰（Ed25519，hex）。可安全公開／開源；用此驗章，無法用此簽發。
# 對應私鑰種子存於 ~/.config/ccgovern/vendor-private.key（chmod 600，務必備份）。
PUBLIC_KEY_HEX = "9d2cfe83f8e84dea1cca604bae57ca58d3dcfe2e9e085ddfc216f8e4487375cd"

# 方案定義（席位上限；價格見 PRICING.md）
TIERS = {
    "founding": {"label": "創始版", "max_seats": 10},
    "team": {"label": "團隊版", "max_seats": 25},
    "enterprise": {"label": "企業版", "max_seats": 0},  # 0 = 無上限
}


@dataclass
class LicenseInfo:
    tier: str
    seats: int
    licensee: str
    issued: str          # YYYY-MM-DD
    updates_until: str    # YYYY-MM-DD（更新權截止；軟體本身永久可用）

    @property
    def tier_label(self) -> str:
        return TIERS.get(self.tier, {}).get("label", self.tier)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _load_vendor_seed(key_file: Path | None = None) -> bytes:
    """讀賣方私鑰種子：優先 env CCGOVERN_VENDOR_KEY（hex），再來 --key-file，
    最後 ~/.config/ccgovern/vendor-private.key。找不到丟 RuntimeError。"""
    env = os.environ.get("CCGOVERN_VENDOR_KEY")
    if env:
        return bytes.fromhex(env.strip())
    candidates = []
    if key_file is not None:
        candidates.append(Path(key_file))
    candidates.append(VENDOR_KEY_FILE)
    for p in candidates:
        if p.exists():
            return bytes.fromhex(p.read_text(encoding="utf-8").strip())
    raise RuntimeError(
        "找不到賣方私鑰：請設定環境變數 CCGOVERN_VENDOR_KEY（hex）、"
        f"用 --key-file 指定，或先執行 `ccgovern-license keygen` 產生 {VENDOR_KEY_FILE}"
    )


def generate_key(
    tier: str,
    seats: int,
    licensee: str,
    issued: str,
    updates_until: str,
    private_seed: bytes | None = None,
    key_file: Path | None = None,
) -> str:
    """簽發授權 key（賣方用；需私鑰種子）。

    private_seed 可直接傳入（測試用）；否則由 env/--key-file/預設檔讀取。
    """
    if tier not in TIERS:
        raise ValueError(f"未知方案：{tier}")
    if private_seed is None:
        private_seed = _load_vendor_seed(key_file)
    payload = json.dumps(
        {"tier": tier, "seats": seats, "licensee": licensee,
         "issued": issued, "updates_until": updates_until},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    b64 = _b64encode(payload.encode("utf-8"))
    sig = ed25519.sign(private_seed, b64.encode("ascii"))
    return f"CCGV2.{b64}.{_b64encode(sig)}"


def verify_key(key: str, public_key_hex: str | None = None) -> LicenseInfo | None:
    """驗證 key；無效回傳 None。public_key_hex 省略時用內嵌公鑰（測試可注入）。"""
    pub_hex = public_key_hex if public_key_hex is not None else PUBLIC_KEY_HEX
    try:
        prefix, b64, sig_b64 = key.strip().split(".")
    except ValueError:
        return None
    if prefix != "CCGV2":
        return None
    try:
        public_key = bytes.fromhex(pub_hex)
        signature = _b64decode(sig_b64)
    except ValueError:
        return None
    if not ed25519.verify(public_key, b64.encode("ascii"), signature):
        return None
    try:
        payload = json.loads(_b64decode(b64).decode("utf-8"))
        return LicenseInfo(
            tier=payload["tier"], seats=int(payload["seats"]),
            licensee=payload["licensee"], issued=payload["issued"],
            updates_until=payload["updates_until"],
        )
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def load_license(path: Path = LICENSE_FILE) -> LicenseInfo | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        return verify_key(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def save_license(key: str, path: Path = LICENSE_FILE) -> tuple[bool, str]:
    info = verify_key(key)
    if info is None:
        return False, "授權 key 無效"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key.strip(), encoding="utf-8")
    return True, f"已啟用 {info.tier_label}（{info.licensee}，{info.seats or '無上限'} 席）"


def trial_banner(dev_count: int, lic: LicenseInfo | None = None,
                 path: Path = LICENSE_FILE) -> str | None:
    """需要顯示浮水印時回傳文字，否則 None。lic 可注入供測試。"""
    if lic is None:
        lic = load_license(path)
    if lic is None:
        if dev_count > FREE_DEV_LIMIT:
            return (f"⚠ 未授權試用：{dev_count} 位開發者已超過免費上限 {FREE_DEV_LIMIT} 位，"
                    f"請購買授權（見 PRICING.md）")
        return None
    if lic.seats and dev_count > lic.seats:
        return f"⚠ 超出授權席位：{dev_count} 位開發者 > {lic.tier_label} {lic.seats} 席，請升級方案"
    return None


def _do_keygen() -> None:
    """產生賣方金鑰對，私鑰寫入 VENDOR_KEY_FILE（chmod 600），印出公鑰與下一步。"""
    seed, public = ed25519.generate_keypair()
    VENDOR_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    VENDOR_KEY_FILE.write_text(seed.hex(), encoding="utf-8")
    os.chmod(VENDOR_KEY_FILE, 0o600)
    pub_hex = public.hex()
    print("✓ 已產生賣方金鑰對（Ed25519）")
    print(f"  私鑰種子已寫入：{VENDOR_KEY_FILE}（chmod 600，請務必備份且勿外洩）")
    print()
    print("公鑰（hex，可公開）：")
    print(f"  {pub_hex}")
    print()
    print("下一步：將 src/ccgovern/license.py 的 PUBLIC_KEY_HEX 更新為上方公鑰：")
    print(f'  PUBLIC_KEY_HEX = "{pub_hex}"')


def main() -> None:
    parser = argparse.ArgumentParser(description="CCGovern 授權管理")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="顯示授權狀態")
    p_act = sub.add_parser("activate", help="啟用授權 key")
    p_act.add_argument("key")
    # 賣方：產生金鑰對
    sub.add_parser("keygen", help="產生賣方 Ed25519 金鑰對（私鑰存本機，印出公鑰）")
    # 賣方簽發（不寫進 README）
    p_mint = sub.add_parser("mint")
    p_mint.add_argument("--tier", required=True, choices=list(TIERS))
    p_mint.add_argument("--seats", type=int, required=True)
    p_mint.add_argument("--licensee", required=True)
    p_mint.add_argument("--issued", required=True)
    p_mint.add_argument("--updates-until", required=True)
    p_mint.add_argument("--key-file", help="賣方私鑰種子檔（hex）；省略時用 env 或預設檔")

    args = parser.parse_args()
    if args.cmd == "activate":
        ok, msg = save_license(args.key)
        print(("✓ " if ok else "✗ ") + msg)
        if not ok:
            raise SystemExit(1)
    elif args.cmd == "keygen":
        _do_keygen()
    elif args.cmd == "mint":
        try:
            print(generate_key(
                args.tier, args.seats, args.licensee, args.issued, args.updates_until,
                key_file=Path(args.key_file) if args.key_file else None,
            ))
        except RuntimeError as e:
            print(f"✗ {e}")
            raise SystemExit(1)
    else:  # status（預設）
        lic = load_license()
        if lic:
            print(f"✓ {lic.tier_label} — {lic.licensee}")
            print(f"  席位：{lic.seats or '無上限'}　簽發：{lic.issued}　更新權至：{lic.updates_until}")
        else:
            print(f"未授權（免費試用，上限 {FREE_DEV_LIMIT} 位開發者；全功能不鎖）")


if __name__ == "__main__":
    main()
