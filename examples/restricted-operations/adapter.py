#!/usr/bin/env python3
"""One-shot examples: fixed report, stream append, or self-wake via JSON stdin.

The operator supplies argv. A transport such as socat supplies only stdin.
This is not a listener, identity service, or sandbox.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


MAX_REQUEST_BYTES = 65536
BACKEND_TIMEOUT = 60


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def read_request(expected):
    line = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
    if len(line) > MAX_REQUEST_BYTES or not line.endswith(b"\n"):
        raise ValueError("expected one bounded JSON line")
    request = json.loads(line.decode("utf-8"), object_pairs_hook=unique_fields)
    if not isinstance(request, dict) or set(request) != expected:
        raise ValueError("unexpected request fields")
    return request


def command(args, request):
    if args.operation == "report":
        text = args.signal if args.signal is not None else request["text"]
        argv = [args.bin, "send", args.to, "--from", args.author, "--stdin",
                "--endpoint", args.endpoint, "--timeout", "15", "--json"]
        if args.wake:
            argv.append("--wake")
    elif args.operation == "append":
        text = request["text"]
        argv = [args.bin, "append", args.stream, "--author", args.author,
                "--stdin", "--state", args.state, "--json"]
    else:
        delay = request["afterSeconds"]
        if type(delay) is not int or not 1 <= delay <= args.max_delay_seconds:
            raise ValueError("delay is outside the configured range")
        return [args.bin, "add", "time", "--after", f"{delay}s", "--to", args.to,
                "--state", args.state, "--endpoint", args.endpoint,
                "--timeout", "15", "--json"], None
    if not isinstance(text, str) or not text.strip():
        raise ValueError("expected nonempty text")
    text.encode("utf-8")
    return argv, text


def receipt(operation, result, status):
    if not isinstance(result, dict):
        raise ValueError("invalid backend result")
    if operation == "report" and result.get("messageOutcome") == "accepted":
        if result.get("outcome") not in {"accepted", "partial"}:
            raise ValueError("invalid message outcome")
        item_id = result["itemId"]
        if not isinstance(item_id, str) or not item_id:
            raise ValueError("missing message receipt")
        public = {"outcome": result["outcome"], "itemId": item_id}
        if "wake" in result:
            wake = result["wake"]
            outcome = wake.get("outcome") if isinstance(wake, dict) else None
            if not isinstance(outcome, str) or outcome not in {
                "confirmedStarted", "confirmedResumed", "notSubmittedActive", "notLoaded",
                "notSubmitted", "rejected", "uncertain", "continuationUnconfirmed", "failed", "partial",
            }:
                outcome = "uncertain"
                public["outcome"], status = "partial", 1
            public["wakeOutcome"] = outcome
        return public, status
    if status == 0 and operation == "append":
        position = result["position"]
        if type(position) is not int or position <= 0:
            raise ValueError("invalid append position")
        return {"outcome": "committed", "position": position}, 0
    if status == 0 and operation == "self-wake":
        job_id = result["job"]["id"]
        if not isinstance(job_id, str) or not job_id:
            raise ValueError("missing job receipt")
        return {"outcome": "scheduled", "jobId": job_id}, 0
    error = result.get("error", {})
    if not isinstance(error, dict):
        raise ValueError("invalid backend error")
    outcome = error.get("outcome", "uncertain")
    if outcome not in {"failed", "partial", "uncertain", "rejected", "notSubmitted"}:
        outcome = "uncertain"
    public = {"outcome": outcome, "code": "backendFailure"}
    if isinstance(error.get("itemId"), str):
        public["itemId"] = error["itemId"]
    return public, 1


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("report", "append", "self-wake"):
        action = sub.add_parser(operation)
        action.add_argument("--bin", required=True, help="absolute backend executable")
        if operation != "append":
            action.add_argument("--to", required=True, help="fixed target thread id")
            action.add_argument("--endpoint", required=True)
        if operation != "report":
            action.add_argument("--state", required=True, help="absolute private state path")
        if operation != "self-wake":
            action.add_argument("--from", dest="author", required=True)
        if operation == "report":
            action.add_argument("--wake", action="store_true")
            action.add_argument("--signal", help="fixed text; request must be {}")
        if operation == "append":
            action.add_argument("--stream", required=True)
        if operation == "self-wake":
            action.add_argument("--max-delay-seconds", type=int, default=86400)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not Path(args.bin).is_absolute():
        parser.error("--bin must be absolute")
    if hasattr(args, "state") and not Path(args.state).is_absolute():
        parser.error("--state must be absolute")
    expected = ({"afterSeconds"} if args.operation == "self-wake"
                else set() if getattr(args, "signal", None) is not None else {"text"})
    try:
        argv, text = command(args, read_request(expected))
    except (ValueError, UnicodeError, OSError, RecursionError):
        public, status = {"outcome": "rejected", "code": "invalidRequest"}, 1
    else:
        try:
            proc = subprocess.run(argv, input=text or "", text=True, encoding="utf-8",
                                  capture_output=True, timeout=BACKEND_TIMEOUT, check=False)
        except OSError:
            public, status = {"outcome": "failed", "code": "backendUnavailable"}, 1
        except subprocess.TimeoutExpired:
            public, status = {"outcome": "uncertain", "code": "backendTimeout"}, 1
        except UnicodeError:
            public, status = {"outcome": "uncertain", "code": "backendFailure"}, 1
        else:
            try:
                public, status = receipt(args.operation, json.loads(proc.stdout), proc.returncode)
            except (ValueError, KeyError, TypeError):
                public, status = {"outcome": "uncertain", "code": "backendFailure"}, 1
    print(json.dumps(public, ensure_ascii=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
