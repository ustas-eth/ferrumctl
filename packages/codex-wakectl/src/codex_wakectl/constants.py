from __future__ import annotations


DEFAULT_TIMEOUT = 20.0
DEFAULT_LEASE_SECONDS = 300
DEFAULT_SYSTEMD_INTERVAL_SECONDS = 30
DELIVERY_LEASE_TIMEOUTS = 10
CLIENT_VERSION = "0.3.4"
SYSTEMD_SERVICE_NAME = "codex-wakectl.service"
SYSTEMD_TIMER_NAME = "codex-wakectl.timer"
STATUS_VALUES = {
    "active",
    "paused",
    "blocked",
    "budgetLimited",
    "usageLimited",
    "complete",
}
TERMINAL_TURN_STATUSES = {"completed", "interrupted", "failed"}
