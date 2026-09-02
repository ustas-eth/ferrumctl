from __future__ import annotations

from collections.abc import AsyncIterator, Collection
from dataclasses import dataclass
from typing import Any

from .appserver import AppServer, list_item_page, list_turn_page, unsupported_method
from .errors import AppServerResponseError, ThreadctlError


Locator = tuple[str, str]

RECENT_TURN_PAGE_LIMIT = 10
# Codex caps thread/turns/list pages at 100 and reconstructs legacy history for
# every page, so exhaustive and anchor-seeking scans should use the full page.
SCAN_TURN_PAGE_LIMIT = 100


@dataclass(frozen=True)
class MaterializedItem:
    turn: dict[str, Any]
    item: dict[str, Any]

    @property
    def locator(self) -> Locator:
        return str(self.turn["id"]), str(self.item["id"])


@dataclass(frozen=True)
class MaterializedSelection:
    entries: list[MaterializedItem]
    backend: str


class UnattributedNativeItems(Exception):
    pass


def turn_entries(turn: dict[str, Any]) -> list[MaterializedItem]:
    turn_id = turn.get("id")
    items = turn.get("items")
    if not isinstance(turn_id, str) or not isinstance(items, list):
        raise ThreadctlError("app-server returned invalid materialized turn data")
    if not all(
        isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and isinstance(item.get("type"), str)
        for item in items
    ):
        raise ThreadctlError("app-server returned invalid materialized item data")
    return [MaterializedItem(turn, item) for item in items]


def placeholder_turn(turn_id: str) -> dict[str, Any]:
    return {
        "id": turn_id,
        "status": None,
        "startedAt": None,
        "completedAt": None,
        "durationMs": None,
        "itemsView": "full",
        "items": [],
    }


def next_cursor(
    page: dict[str, Any],
    seen: set[str],
    *,
    label: str,
) -> str | None:
    cursor = page.get("nextCursor")
    if cursor is None:
        return None
    if not isinstance(cursor, str) or cursor in seen:
        raise ThreadctlError(f"app-server returned an invalid {label} cursor")
    seen.add(cursor)
    return cursor


async def find_turn(
    app: AppServer,
    thread_id: str,
    turn_id: str,
    *,
    items_view: str,
) -> dict[str, Any]:
    async for turns in reverse_turn_pages(
        app,
        thread_id,
        items_view=items_view,
        page_limit=50,
    ):
        for turn in turns:
            if turn.get("id") == turn_id:
                return turn
    raise ThreadctlError(f"turn not found: {turn_id}")


async def reverse_turn_pages(
    app: AppServer,
    thread_id: str,
    *,
    items_view: str,
    page_limit: int,
) -> AsyncIterator[list[dict[str, Any]]]:
    cursor: str | None = None
    seen: set[str] = set()
    while True:
        page = await list_turn_page(
            app,
            thread_id,
            cursor=cursor,
            limit=page_limit,
            sort_direction="desc",
            items_view=items_view,
        )
        turns = page["data"]
        yield turns
        cursor = next_cursor(page, seen, label="turn pagination")
        if cursor is None:
            return


async def native_turn_entries(
    app: AppServer,
    thread_id: str,
    turn_id: str,
) -> list[MaterializedItem]:
    items: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    while True:
        page = await list_item_page(
            app,
            thread_id,
            turn_id=turn_id,
            cursor=cursor,
            limit=100,
            sort_direction="asc",
        )
        for entry in page["data"]:
            wrapped_item = entry.get("item")
            wrapped_turn_id = entry.get("turnId")
            if not isinstance(wrapped_turn_id, str) or not isinstance(
                wrapped_item, dict
            ):
                items.append(entry)
                continue
            if wrapped_turn_id != turn_id:
                raise ThreadctlError(
                    "app-server returned an item from an unexpected turn"
                )
            items.append(wrapped_item)
        cursor = next_cursor(page, seen, label="item pagination")
        if cursor is None:
            break

    try:
        turn = await find_turn(app, thread_id, turn_id, items_view="summary")
    except AppServerResponseError as exc:
        if not unsupported_method(exc):
            raise
        turn = placeholder_turn(turn_id)
    materialized = dict(turn)
    materialized["items"] = items
    materialized["itemsView"] = "full"
    return turn_entries(materialized)


async def exact_turn_entries(
    app: AppServer,
    thread_id: str,
    turn_id: str,
) -> MaterializedSelection:
    try:
        entries = await native_turn_entries(app, thread_id, turn_id)
    except AppServerResponseError as exc:
        if not unsupported_method(exc):
            raise
    else:
        return MaterializedSelection(entries, "thread/items/list")

    turn = await find_turn(app, thread_id, turn_id, items_view="full")
    return MaterializedSelection(turn_entries(turn), "thread/turns/list")


def wrapped_native_entry(entry: dict[str, Any]) -> MaterializedItem:
    turn_id = entry.get("turnId")
    item = entry.get("item")
    if not isinstance(turn_id, str) or not isinstance(item, dict):
        raise UnattributedNativeItems
    return MaterializedItem(placeholder_turn(turn_id), item)


async def native_thread_entries(
    app: AppServer,
    thread_id: str,
    *,
    after: Locator | None,
    before: Locator | None,
    types: Collection[str] | None,
    limit: int,
) -> list[MaterializedItem]:
    newest_first: list[MaterializedItem] = []
    cursor: str | None = None
    seen: set[str] = set()

    while True:
        page = await list_item_page(
            app,
            thread_id,
            cursor=cursor,
            limit=100,
            sort_direction="desc",
        )
        newest_first.extend(wrapped_native_entry(entry) for entry in page["data"])
        entries = list(reversed(newest_first))
        locators = {entry.locator for entry in entries}
        found_after = after is None or after in locators
        found_before = before is None or before in locators

        if after is None and before is None:
            if limit and sum(1 for entry in entries if matches_type(entry, types)) >= limit:
                return entries
        elif found_after and found_before:
            if after is not None:
                return entries
            if limit:
                selected = range_entries(entries, after=None, before=before)
                if sum(1 for entry in selected if matches_type(entry, types)) >= limit:
                    return entries

        cursor = next_cursor(page, seen, label="item pagination")
        if cursor is None:
            return entries


async def enrich_turn_metadata(
    app: AppServer,
    thread_id: str,
    entries: list[MaterializedItem],
) -> list[MaterializedItem]:
    missing = {entry.locator[0] for entry in entries}
    if not missing:
        return entries

    metadata: dict[str, dict[str, Any]] = {}
    try:
        async for turns in reverse_turn_pages(
            app,
            thread_id,
            items_view="summary",
            page_limit=50,
        ):
            for turn in turns:
                turn_id = turn["id"]
                if turn_id in missing:
                    metadata[turn_id] = turn
                    missing.remove(turn_id)
            if not missing:
                break
    except AppServerResponseError as exc:
        if not unsupported_method(exc):
            raise

    return [
        MaterializedItem(metadata.get(entry.locator[0], entry.turn), entry.item)
        for entry in entries
    ]


def summary_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first_user = next(
        (item for item in items if item.get("type") == "userMessage"),
        None,
    )
    final_agent = next(
        (item for item in reversed(items) if item.get("type") == "agentMessage"),
        None,
    )
    if (
        first_user is not None
        and final_agent is not None
        and first_user.get("id") != final_agent.get("id")
    ):
        return [first_user, final_agent]
    if first_user is not None:
        return [first_user]
    if final_agent is not None:
        return [final_agent]
    return []


async def native_inspection_history(
    app: AppServer,
    thread_id: str,
    *,
    turn_limit: int,
    item_limit: int,
    brief: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    newest: list[tuple[str | None, dict[str, Any]]] = []
    cursor: str | None = None
    seen: set[str] = set()
    attributed = True
    target_items = item_limit if item_limit > 0 else None

    while True:
        page = await list_item_page(
            app,
            thread_id,
            cursor=cursor,
            limit=100,
            sort_direction="desc",
        )
        for entry in page["data"]:
            turn_id = entry.get("turnId")
            item = entry.get("item")
            if isinstance(turn_id, str) and isinstance(item, dict):
                newest.append((turn_id, item))
            else:
                attributed = False
                newest.append((None, entry))

        if attributed:
            seen_turns = list(dict.fromkeys(turn_id for turn_id, _ in newest))
            if len(seen_turns) > turn_limit:
                break
        else:
            matching = (
                sum(
                    1
                    for _, item in newest
                    if item.get("type") in {"userMessage", "agentMessage"}
                )
                if brief
                else len(newest)
            )
            if target_items is not None and matching >= target_items:
                break

        cursor = next_cursor(page, seen, label="item pagination")
        if cursor is None:
            break

    if not attributed:
        items = [item for _, item in newest]
        if brief:
            items = [
                item
                for item in items
                if item.get("type") in {"userMessage", "agentMessage"}
            ]
        if target_items is not None:
            items = items[:target_items]
        items.reverse()
        return [], items

    newest_turn_ids = list(
        dict.fromkeys(turn_id for turn_id, _ in newest if turn_id is not None)
    )[:turn_limit]
    selected = [
        MaterializedItem(placeholder_turn(turn_id), item)
        for turn_id, item in reversed(newest)
        if turn_id in newest_turn_ids
    ]
    selected = await enrich_turn_metadata(app, thread_id, selected)

    turns: list[dict[str, Any]] = []
    for turn_id in newest_turn_ids:
        matching = [entry for entry in selected if entry.locator[0] == turn_id]
        metadata = dict(matching[0].turn) if matching else placeholder_turn(turn_id)
        items = [entry.item for entry in matching]
        metadata["items"] = summary_items(items) if brief else items
        metadata["itemsView"] = "summary" if brief else "full"
        turns.append(metadata)
    return turns, []


async def all_turn_entries(
    app: AppServer,
    thread_id: str,
) -> list[MaterializedItem]:
    newest_first: list[list[MaterializedItem]] = []
    async for turns in reverse_turn_pages(
        app,
        thread_id,
        items_view="full",
        page_limit=SCAN_TURN_PAGE_LIMIT,
    ):
        newest_first.extend(turn_entries(turn) for turn in turns)
    return chronological(newest_first)


def chronological(
    newest_first: list[list[MaterializedItem]],
) -> list[MaterializedItem]:
    return [entry for batch in reversed(newest_first) for entry in batch]


async def bounded_turn_entries(
    app: AppServer,
    thread_id: str,
    *,
    after: Locator | None,
    before: Locator | None,
    types: Collection[str] | None,
    limit: int,
) -> list[MaterializedItem]:
    newest_first: list[list[MaterializedItem]] = []
    async for turns in reverse_turn_pages(
        app,
        thread_id,
        items_view="full",
        page_limit=SCAN_TURN_PAGE_LIMIT,
    ):
        newest_first.extend(turn_entries(turn) for turn in turns)
        entries = chronological(newest_first)
        locators = {entry.locator for entry in entries}
        found_after = after is None or after in locators
        found_before = before is None or before in locators

        if found_after and found_before:
            if after is not None:
                return entries
            if limit:
                selected = range_entries(entries, after=None, before=before)
                if sum(
                    1 for entry in selected if matches_type(entry, types)
                ) >= limit:
                    return entries
    return chronological(newest_first)


async def recent_turn_entries(
    app: AppServer,
    thread_id: str,
    *,
    types: Collection[str] | None,
    limit: int,
) -> list[MaterializedItem]:
    newest_first: list[list[MaterializedItem]] = []
    count = 0
    async for turns in reverse_turn_pages(
        app,
        thread_id,
        items_view="full",
        page_limit=RECENT_TURN_PAGE_LIMIT,
    ):
        for turn in turns:
            entries = turn_entries(turn)
            newest_first.append(entries)
            count += sum(1 for entry in entries if matches_type(entry, types))
        if limit and count >= limit:
            break

    selected = [
        entry
        for entry in chronological(newest_first)
        if matches_type(entry, types)
    ]
    return selected if limit == 0 else selected[-limit:]


def matches_type(
    entry: MaterializedItem,
    types: Collection[str] | None,
) -> bool:
    return not types or entry.item["type"] in types


def range_entries(
    entries: list[MaterializedItem],
    *,
    after: Locator | None,
    before: Locator | None,
) -> list[MaterializedItem]:
    positions: dict[Locator, list[int]] = {}
    for index, entry in enumerate(entries):
        positions.setdefault(entry.locator, []).append(index)

    def resolve(locator: Locator, label: str) -> int:
        matches = positions.get(locator, [])
        rendered = f"{locator[0]} {locator[1]}"
        if not matches:
            raise ThreadctlError(f"{label} item not found: {rendered}")
        if len(matches) > 1:
            raise ThreadctlError(f"{label} item is ambiguous: {rendered}")
        return matches[0]

    start = resolve(after, "after") + 1 if after is not None else 0
    end = resolve(before, "before") if before is not None else len(entries)
    if after is not None and before is not None and start > end:
        raise ThreadctlError("after item must precede before item")
    return entries[start:end]


async def select_materialized_items(
    app: AppServer,
    thread_id: str,
    *,
    turn_id: str | None = None,
    after: Locator | None = None,
    before: Locator | None = None,
    types: Collection[str] | None = None,
    limit: int = 20,
) -> MaterializedSelection:
    if limit < 0:
        raise ThreadctlError("item limit must be zero or greater")

    native_unattributed = False
    if turn_id is None:
        try:
            entries = await native_thread_entries(
                app,
                thread_id,
                after=after,
                before=before,
                types=types,
                limit=limit,
            )
        except AppServerResponseError as exc:
            if not unsupported_method(exc):
                raise
        except UnattributedNativeItems:
            native_unattributed = True
        else:
            entries = range_entries(entries, after=after, before=before)
            entries = [entry for entry in entries if matches_type(entry, types)]
            if limit:
                entries = entries[:limit] if after is not None else entries[-limit:]
            entries = await enrich_turn_metadata(app, thread_id, entries)
            return MaterializedSelection(entries, "thread/items/list")

    try:
        if turn_id is not None:
            selection = await exact_turn_entries(app, thread_id, turn_id)
            entries = selection.entries
            backend = selection.backend
        elif after is not None or before is not None:
            entries = await bounded_turn_entries(
                app,
                thread_id,
                after=after,
                before=before,
                types=types,
                limit=limit,
            )
            backend = "thread/turns/list"
        elif limit == 0:
            entries = await all_turn_entries(app, thread_id)
            backend = "thread/turns/list"
        else:
            entries = await recent_turn_entries(
                app,
                thread_id,
                types=types,
                limit=limit,
            )
            return MaterializedSelection(entries, "thread/turns/list")
    except AppServerResponseError as exc:
        if native_unattributed and unsupported_method(exc):
            raise ThreadctlError(
                "this Codex version does not expose turn ids for thread-wide "
                "item history; select one turn with --turn"
            ) from exc
        raise

    entries = range_entries(entries, after=after, before=before)
    entries = [entry for entry in entries if matches_type(entry, types)]
    if limit:
        entries = entries[:limit] if after is not None else entries[-limit:]
    return MaterializedSelection(entries, backend)
