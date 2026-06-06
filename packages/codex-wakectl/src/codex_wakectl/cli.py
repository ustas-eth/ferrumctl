from __future__ import annotations

import argparse
import asyncio
import sys

import websockets

from .appserver import (
    AppServer,
    connect_websocket,
    get_goal,
    get_thread_status,
    list_loaded,
    resolve_unix_endpoint,
    send_turn,
    status_name,
    thread_is_active,
)
from .commands import (
    cmd_add,
    cmd_cancel,
    cmd_list,
    cmd_loaded,
    cmd_run,
    cmd_send,
    cmd_status,
    cmd_systemd_install,
    cmd_systemd_uninstall,
    cmd_wait,
    seed_repeating_goal_job,
)
from .conditions import (
    build_cmd_condition,
    build_goal_condition,
    build_stop_condition,
    build_time_condition,
    cmd_condition_ready,
    condition_needs_app,
    condition_ready,
    condition_repeats,
    goal_condition_ready,
    max_fires_reached,
    new_job,
    stop_condition_ready,
    time_condition_ready,
)
from .constants import (
    CLIENT_VERSION,
    DEFAULT_LEASE_SECONDS,
    DEFAULT_SYSTEMD_INTERVAL_SECONDS,
    DEFAULT_TIMEOUT,
    STATUS_VALUES,
    SYSTEMD_SERVICE_NAME,
    SYSTEMD_TIMER_NAME,
)
from .errors import WakectlError
from .parser import (
    add_cmd_condition_parser,
    add_global_options,
    add_goal_condition_options,
    add_goal_condition_parser,
    add_json_option,
    add_state_json_options,
    add_stop_condition_parser,
    add_target_message,
    add_time_condition_parser,
    add_wait_cmd_condition_parser,
    add_wait_goal_condition_parser,
    add_wait_options,
    add_wait_stop_condition_parser,
    add_wait_time_condition_parser,
    build_parser,
)
from .parsing import (
    format_time,
    now_seconds,
    parse_at,
    parse_duration,
    parse_positive_float,
    parse_positive_int,
    parse_statuses,
)
from .state import (
    JOB_COLUMNS,
    OPTIONAL_JOB_FIELDS,
    cancel_job,
    claim_pending_jobs,
    decode_job,
    default_state_path,
    encode_value,
    ensure_column,
    insert_job,
    list_jobs,
    open_state,
    update_claimed_job,
)
from .systemd import (
    build_systemd_units,
    quote_systemd_arg,
    resolve_wakectl_bin,
    run_systemctl,
    systemd_user_dir,
)


async def dispatch(args: argparse.Namespace) -> int:
    result = args.func(args)
    if asyncio.iscoroutine(result):
        return await result
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(dispatch(args))
    except BrokenPipeError:
        return 1
    except (OSError, WakectlError, websockets.WebSocketException) as exc:
        print(f"codex-wakectl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
