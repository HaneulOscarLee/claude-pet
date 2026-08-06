"""Shared state between the Claude Code hooks and the overlay.

Hooks run on every tool call, so writes have to be cheap and must never block
Claude Code: this module is stdlib-only and every write is an atomic replace
guarded by a short-lived lock file.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

#: Pet states the overlay knows how to render, most urgent first. The names
#: match the animation rows of the Codex pet contract.
PRIORITY: tuple[str, ...] = (
    "waiting",   # Claude is blocked on the user -- the one we most want seen
    "failed",
    "review",    # turn finished, output is waiting to be read
    "running",
    "waving",
    "idle",
)

#: Sessions quieter than this are treated as gone.
SESSION_TTL_SECONDS = 6 * 60 * 60

#: How long a state stays interesting *for the session that reported it*.
#: Past this, that session counts as idle when aggregating, so a finished
#: session announces itself and then stops speaking for the others. States
#: absent here never expire: `waiting` must keep asking, and `running` ends
#: only when Claude says so.
DWELL_SECONDS: dict[str, float] = {"waving": 3.0, "review": 20.0, "failed": 20.0}


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "claude-pet"


def state_path() -> Path:
    return state_dir() / "state.json"


def pid_path() -> Path:
    return state_dir() / "overlay.pid"


def _empty() -> dict[str, Any]:
    return {"version": 1, "updated": 0.0, "sessions": {}}


def read() -> dict[str, Any]:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), dict):
        return _empty()
    return data


def _write(data: dict[str, Any]) -> None:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
        os.replace(temporary, state_path())
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _prune(sessions: dict[str, Any], now: float) -> None:
    for session_id, session in list(sessions.items()):
        timestamp = session.get("ts")
        if not isinstance(timestamp, (int, float)) or now - timestamp > SESSION_TTL_SECONDS:
            sessions.pop(session_id, None)


def update(session_id: str, **fields: Any) -> dict[str, Any]:
    """Merge `fields` into `session_id`'s entry and persist.

    A `state` of None removes the session. Contention is resolved by a lock
    file with a hard timeout -- a stuck lock must never wedge a Claude turn.
    """
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / "state.lock"

    deadline = time.monotonic() + 1.0
    acquired = False
    while True:
        try:
            file_descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(file_descriptor)
            acquired = True
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                # Assume the holder died; steal the lock rather than give up.
                break
            time.sleep(0.01)

    try:
        data = read()
        sessions = data["sessions"]
        now = time.time()
        _prune(sessions, now)

        if fields.get("state", "") is None:
            sessions.pop(session_id, None)
        else:
            session = sessions.get(session_id) or {}
            session.update({key: value for key, value in fields.items() if value is not None})
            session["ts"] = now
            sessions[session_id] = session

        data["updated"] = now
        _write(data)
        return data
    finally:
        if acquired or lock.exists():
            try:
                lock.unlink()
            except OSError:
                pass


def effective_state(session: dict[str, Any], now: float) -> str:
    """The state this session still deserves to speak for, given its dwell."""
    reported = session.get("state")
    if reported not in PRIORITY:
        return "idle"
    dwell = DWELL_SECONDS.get(reported)
    if dwell is not None and now - session["ts"] > dwell:
        return "idle"
    return reported


def aggregate(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Collapse every live session into the one state the pet should show.

    Time-dependent: the same file aggregates differently as dwells expire, so
    callers should re-run this on a timer rather than only on file changes.
    """
    data = read() if data is None else data
    now = time.time()
    live = [
        session
        for session in data.get("sessions", {}).values()
        if isinstance(session, dict)
        and isinstance(session.get("ts"), (int, float))
        and now - session["ts"] <= SESSION_TTL_SECONDS
    ]
    if not live:
        return {"state": "idle", "sessions": 0, "detail": "", "cwd": "", "since": now}

    order = {name: index for index, name in enumerate(PRIORITY)}
    ranked = [(effective_state(session, now), session) for session in live]
    state_name, winner = min(
        ranked, key=lambda pair: (order.get(pair[0], len(PRIORITY)), -pair[1]["ts"])
    )
    return {
        "state": state_name,
        "sessions": len(live),
        # An expired session has nothing left to say, so drop its stale detail.
        "detail": str(winner.get("detail") or "") if state_name != "idle" else "",
        "cwd": str(winner.get("cwd") or ""),
        "since": winner.get("ts", now),
    }
