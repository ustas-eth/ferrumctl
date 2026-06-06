from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .constants import SYSTEMD_SERVICE_NAME, SYSTEMD_TIMER_NAME
from .errors import WakectlError


def systemd_user_dir() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "systemd" / "user"


def resolve_wakectl_bin() -> str:
    path = shutil.which("codex-wakectl")
    if path is None:
        raise WakectlError("codex-wakectl is not on PATH; install it before installing units")
    return path


def quote_systemd_arg(value: str) -> str:
    if re.match(r"^[A-Za-z0-9_@%+=:,./-]+$", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_systemd_units(
    *,
    wakectl_bin: str,
    state: Path,
    interval_seconds: int,
) -> tuple[str, str]:
    exec_start = " ".join(
        quote_systemd_arg(part)
        for part in [wakectl_bin, "--state", str(state), "run"]
    )
    service = f"""[Unit]
Description=Process codex-wakectl wake jobs

[Service]
Type=oneshot
ExecStart={exec_start}
"""
    timer = f"""[Unit]
Description=Run codex-wakectl wake jobs every {interval_seconds}s

[Timer]
OnActiveSec={interval_seconds}s
OnUnitInactiveSec={interval_seconds}s
AccuracySec=1s

[Install]
WantedBy=timers.target
"""
    return service, timer


def run_systemctl(args: list[str], *, check: bool = True) -> None:
    proc = subprocess.run(
        ["systemctl", "--user", *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and proc.returncode != 0:
        output = (proc.stderr or proc.stdout).strip()
        command = "systemctl --user " + " ".join(args)
        raise WakectlError(f"{command} failed: {output}")
