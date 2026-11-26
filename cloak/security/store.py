"""Encrypted spill store: rendered outputs stay in memory while small, then go to AES-GCM files under TMPDIR.

The key is derived from RAKSHA_SECRET (HKDF "at-rest") and never stored. Files are removed by `close()`, by
`finally`, at exit and on SIGTERM/SIGINT (see cleanup.py). Nothing here is part of the release.
"""
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cloak.security import cleanup


class SpillStore:
    def __init__(self, key: bytes, threshold_bytes: int):
        self._aead = AESGCM(key)
        self._threshold = threshold_bytes
        self._mem = {}
        self._files = {}
        self._dir = None
        self._n = 0
        self._mem_bytes = 0
        self.spilled = 0

    def put(self, data: bytes) -> int:
        h = self._n
        self._n += 1
        if self._mem_bytes + len(data) <= self._threshold:
            self._mem[h] = data
            self._mem_bytes += len(data)
            return h
        if self._dir is None:
            self._dir = tempfile.mkdtemp(prefix="cc_", dir=os.environ.get("TMPDIR") or None)
            cleanup.register(self._dir)
        nonce = h.to_bytes(12, "big")  # unique per blob under this run's key
        path = Path(self._dir) / f"{h}.bin"
        path.write_bytes(self._aead.encrypt(nonce, data, None))
        self._files[h] = path
        self.spilled += 1
        return h

    def get(self, h: int) -> bytes:
        if h in self._mem:
            return self._mem[h]
        return self._aead.decrypt(h.to_bytes(12, "big"), self._files[h].read_bytes(), None)

    def close(self) -> None:
        self._mem.clear()
        self._files.clear()
        if self._dir:
            cleanup.cleanup()
            self._dir = None
