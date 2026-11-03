"""Inspect or replace local recovery records without changing live settings."""
from __future__ import annotations

import argparse
import json

from .agents import is_agent_path, resolve_thread_reference
from .appserver import AppServer, normalize_endpoint
from .config_input import read_config_file
from .recovery import public_recovery, read_recovery, recovery_config, write_recovery


async def cmd_recovery(args: argparse.Namespace) -> int:
    config = read_config_file(args.config_file)
    if config is not None:
        config = recovery_config(config)
    endpoint = normalize_endpoint(args.endpoint)
    target = args.thread_id
    if is_agent_path(target):
        async with AppServer(endpoint, args.timeout) as app:
            target = await resolve_thread_reference(app, target, tree_thread_id=args.tree)
    if config is not None:
        result = write_recovery(args.state, endpoint, target, config)
        result["outcome"] = "replaced"
        if args.values and config:
            result["config"] = config
    elif args.forget:
        # A corrupt payload must not prevent removal of its exact record.
        result = (write_recovery(args.state, endpoint, target, {}) if args.state.expanduser().exists()
                  else public_recovery(args.state, endpoint, target, None))
        result["outcome"] = "forgotten"
    else:
        record = read_recovery(args.state, endpoint, target)
        result = public_recovery(args.state, endpoint, target, record, values=args.values)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['outcome']}\t{target}\tkeys=" + ",".join(result["keys"]))
        if "config" in result:
            print(json.dumps(result["config"], indent=2))
    return 0
