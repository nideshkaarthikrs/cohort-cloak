"""Sub-keys derived from RAKSHA_SECRET with HKDF. Held in memory only, never written or printed."""
import base64
import hashlib
import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32


def _derive(secret: bytes, label: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"cohort-cloak/v1", info=label).derive(secret)


class Keys:
    __slots__ = ("psn_key", "shift_key", "at_rest_key")

    def __init__(self, secret: bytes):
        self.psn_key = _derive(secret, b"psn")
        self.shift_key = _derive(secret, b"shift")
        self.at_rest_key = _derive(secret, b"at-rest")

    def __repr__(self) -> str:
        return "Keys(<redacted>)"

    __str__ = __repr__

    def pseudonym(self, cluster_key: str) -> str:
        digest = hmac.new(self.psn_key, cluster_key.encode("utf-8"), hashlib.sha256).digest()
        n = int.from_bytes(digest[:5], "big")
        return "PSN-" + "".join(_ALPHABET[(n >> (5 * i)) & 31] for i in range(6))

    def date_shift_days(self, psn: str, max_days: int) -> int:
        """Per-patient shift in [-max, +max], never 0."""
        d = hmac.new(self.shift_key, psn.encode("utf-8"), hashlib.sha256).digest()
        v = int.from_bytes(d[:4], "big") % (2 * max_days + 1) - max_days
        return v if v != 0 else 1

    def at_rest_b64(self) -> str:
        return base64.urlsafe_b64encode(self.at_rest_key).decode("ascii")
