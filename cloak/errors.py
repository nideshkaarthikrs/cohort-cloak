"""Quarantine signalling. Codes are snake_case enums; they never carry file content."""
import re


class Quarantine(Exception):
    """Raised when a file cannot be processed safely. `code` is a snake_case reason."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

    def __str__(self) -> str:  # never anything but the enum
        return self.code


def reason_for(exc: BaseException) -> str:
    """Snake_case reason from an exception: the enum for Quarantine, else the class name only."""
    if isinstance(exc, Quarantine):
        return exc.code
    name = type(exc).__name__
    return "error_" + re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
