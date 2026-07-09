from __future__ import annotations


class WakectlError(RuntimeError):
    pass


class WakeDeferred(WakectlError):
    """The wake is valid but its target cannot accept it yet."""
