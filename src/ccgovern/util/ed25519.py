"""純 Python Ed25519 簽章（RFC 8032）。

零外部相依：只用 hashlib.sha512 與整數運算，照 RFC 8032 §6 的參考實作慣例寫成。
每次 CLI 呼叫 / 載入授權只跑一次，效能無關緊要。

公開 API：
    generate_keypair(seed=None) -> (private_seed_bytes32, public_key_bytes32)
    sign(private_seed, message) -> bytes64
    verify(public_key, message, signature) -> bool

正確性以 RFC 8032 §7.1 測試向量驗證（見 tests/test_license.py）。
"""

from __future__ import annotations

import hashlib
import os

# Ed25519 曲線參數（RFC 8032 §5.1）
_b = 256
_q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_d = -121665 * pow(121666, _q - 2, _q) % _q
_I = pow(2, (_q - 1) // 4, _q)


def _H(m: bytes) -> bytes:
    return hashlib.sha512(m).digest()


def _inv(x: int) -> int:
    return pow(x, _q - 2, _q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_d * y * y + 1)
    x = pow(xx, (_q + 3) // 8, _q)
    if (x * x - xx) % _q != 0:
        x = (x * _I) % _q
    if x % 2 != 0:
        x = _q - x
    return x


_By = 4 * _inv(5) % _q
_Bx = _xrecover(_By)
_B = (_Bx % _q, _By % _q, 1, (_Bx * _By) % _q)  # extended coords (X, Y, Z, T)


def _edwards_add(P, Q):
    (x1, y1, z1, t1) = P
    (x2, y2, z2, t2) = Q
    a = (y1 - x1) * (y2 - x2) % _q
    b = (y1 + x1) * (y2 + x2) % _q
    c = t1 * 2 * _d * t2 % _q
    dd = z1 * 2 * z2 % _q
    e = b - a
    f = dd - c
    g = dd + c
    h = b + a
    x3 = e * f
    y3 = g * h
    t3 = e * h
    z3 = f * g
    return (x3 % _q, y3 % _q, z3 % _q, t3 % _q)


def _scalarmult(P, e: int):
    if e == 0:
        return (0, 1, 1, 0)
    Q = _scalarmult(P, e // 2)
    Q = _edwards_add(Q, Q)
    if e & 1:
        Q = _edwards_add(Q, P)
    return Q


def _encode_point(P) -> bytes:
    (x, y, z, t) = P
    zi = _inv(z)
    x = (x * zi) % _q
    y = (y * zi) % _q
    bits = [(y >> i) & 1 for i in range(_b - 1)] + [x & 1]
    return bytes(
        sum(bits[i * 8 + j] << j for j in range(8)) for i in range(_b // 8)
    )


def _bit(h: bytes, i: int) -> int:
    return (h[i // 8] >> (i % 8)) & 1


def _clamp(h: bytes) -> int:
    a = 2 ** (_b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, _b - 2))
    return a


def _public_from_seed(seed: bytes) -> bytes:
    h = _H(seed)
    a = _clamp(h)
    A = _scalarmult(_B, a)
    return _encode_point(A)


def generate_keypair(seed: bytes | None = None) -> tuple[bytes, bytes]:
    """產生金鑰對；seed 省略時用 os.urandom。回傳 (私鑰種子32, 公鑰32)。"""
    if seed is None:
        seed = os.urandom(32)
    if len(seed) != 32:
        raise ValueError("seed 必須為 32 bytes")
    return seed, _public_from_seed(seed)


def sign(private_seed: bytes, message: bytes) -> bytes:
    """以私鑰種子簽訊息，回傳 64-byte 簽章。"""
    if len(private_seed) != 32:
        raise ValueError("private_seed 必須為 32 bytes")
    h = _H(private_seed)
    a = _clamp(h)
    A = _encode_point(_scalarmult(_B, a))
    r = int.from_bytes(_H(h[_b // 8:] + message), "little") % _L
    R = _encode_point(_scalarmult(_B, r))
    k = int.from_bytes(_H(R + A + message), "little") % _L
    s = (r + k * a) % _L
    return R + s.to_bytes(32, "little")


def _decode_point(s: bytes):
    y = int.from_bytes(s, "little") & ((1 << (_b - 1)) - 1)
    x = _xrecover(y)
    if x & 1 != _bit(s, _b - 1):
        x = _q - x
    P = (x % _q, y % _q, 1, (x * y) % _q)
    return P


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """驗證簽章；有效回傳 True，否則 False（不丟例外）。"""
    try:
        if len(signature) != 64 or len(public_key) != 32:
            return False
        R = signature[:32]
        s = int.from_bytes(signature[32:], "little")
        if s >= _L:
            return False
        A = _decode_point(public_key)
        Rp = _decode_point(R)
        k = int.from_bytes(_H(R + public_key + message), "little") % _L
        left = _scalarmult(_B, s)
        right = _edwards_add(Rp, _scalarmult(A, k))
        return _encode_point(left) == _encode_point(right)
    except (ValueError, IndexError):
        return False
