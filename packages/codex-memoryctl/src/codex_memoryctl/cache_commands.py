from __future__ import annotations

import argparse
import json
from pathlib import Path

from .cache import clear_cache, inspect_cache


async def cmd_cache_info(args: argparse.Namespace) -> int:
    info = inspect_cache(Path(args.database))
    output = {
        "operation": "cache-info",
        "database": str(info.path),
        "exists": info.exists,
        "entryCount": info.entry_count,
        "sizeBytes": info.size_bytes,
        "oldestAt": info.oldest_at,
        "newestAt": info.newest_at,
        "operations": info.operations,
    }
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"database={info.path}")
        print(f"exists={'yes' if info.exists else 'no'}")
        print(f"entries={info.entry_count}")
        print(f"sizeBytes={info.size_bytes}")
        for operation, count in info.operations.items():
            print(f"{operation}={count}")
        if info.oldest_at is not None:
            print(f"oldestAt={info.oldest_at}")
            print(f"newestAt={info.newest_at}")
    return 0


async def cmd_cache_clear(args: argparse.Namespace) -> int:
    path = Path(args.database).expanduser().resolve()
    count = clear_cache(path)
    output = {
        "operation": "cache-clear",
        "database": str(path),
        "clearedCount": count,
    }
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"cleared {count} cached description(s) from {path}")
    return 0
