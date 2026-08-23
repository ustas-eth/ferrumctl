class MemoryctlError(Exception):
    """Expected command failure."""


class InjectionUncertain(MemoryctlError):
    """An injection request may have succeeded before communication failed."""

    def __init__(self, target: str, memory_ids: list[str]):
        joined = ", ".join(memory_ids)
        super().__init__(
            f"injection outcome is uncertain for {target}; "
            f"inspect the target rollout for {joined} before retrying"
        )
