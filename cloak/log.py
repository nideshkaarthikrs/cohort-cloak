"""PII-free logger. Only enum names and integers are accepted, so content cannot leak."""
import re
from pathlib import Path

_ENUM = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class RunLog:
    def __init__(self, path: Path = None):
        self._fh = None
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(path, "w", encoding="utf-8", newline="\n")

    def event(self, name: str, **fields) -> None:
        if not _ENUM.match(name):
            raise ValueError("bad_event")
        parts = [name]
        for k in sorted(fields):
            v = fields[k]
            if not _ENUM.match(k):
                raise ValueError("bad_field")
            if isinstance(v, bool) or not isinstance(v, int):
                if isinstance(v, str) and _ENUM.match(v):
                    parts.append(f"{k}={v}")
                    continue
                raise ValueError("bad_value")
            parts.append(f"{k}={v}")
        if self._fh:
            self._fh.write(" ".join(parts) + "\n")

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
