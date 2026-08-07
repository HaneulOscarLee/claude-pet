"""Recording where a Claude session lives, so the pet can jump back to it.

Collected by the hook, which runs on every tool call, so this only reads
`/proc` and the environment -- no X queries, no subprocesses. Resolving those
pids to an actual window is the overlay's job, and only when clicked.

Stdlib only.
"""

from __future__ import annotations

import os
from typing import Any

from . import desktop

#: Processes between the hook and the terminal that are never the terminal.
_TRANSPARENT = {
    "bash", "sh", "zsh", "fish", "dash", "python3", "python", "node",
    "claude", "claude-pet", "tmux", "tmux: server", "su", "sudo", "env",
}

_MAX_DEPTH = 16


def _parent_of(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as stream:
            for line in stream:
                if line.startswith("PPid:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _comm(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/comm", encoding="utf-8") as stream:
            return stream.read().strip()
    except OSError:
        return ""


def ancestor_pids() -> list[int]:
    """Pids from this process up to init, nearest first.

    The terminal emulator is somewhere in here. Which one it is cannot be known
    without asking the window server, so the whole chain is recorded and the
    overlay matches it against window ownership later.
    """
    chain: list[int] = []
    pid = os.getpid()
    for _ in range(_MAX_DEPTH):
        parent = _parent_of(pid)
        if parent is None or parent <= 1:
            break
        chain.append(parent)
        pid = parent
    return chain


def terminal_candidates() -> list[int]:
    """Ancestors that could plausibly own a terminal window."""
    return [pid for pid in ancestor_pids() if _comm(pid) not in _TRANSPARENT]


#: `comm` of the Claude Code process. Recorded separately as the session's
#: liveness signal: the rest of the ancestor chain is useless for that, since
#: it ends at systemd, which never exits.
CLAUDE_COMM = "claude"


def claude_pid() -> int | None:
    """Nearest ancestor that is the Claude Code process itself."""
    for pid in ancestor_pids():
        if _comm(pid) == CLAUDE_COMM:
            return pid
    return None


def locator() -> dict[str, Any]:
    """Everything known about where this session is running."""
    chain = ancestor_pids()[:_MAX_DEPTH]
    found: dict[str, Any] = {"pids": chain}

    owner = claude_pid()
    if owner is not None:
        found["claude_pid"] = owner

    # Claude Desktop runs the same Claude Code binary, so its sessions arrive
    # here indistinguishably -- except in the ancestry. Recording which side a
    # session came from now is the only chance to know: the app is
    # Wayland-native, so afterwards it owns no window to recognise it by.
    found["origin"] = desktop.origin_of(chain)

    pane = os.environ.get("TMUX_PANE")
    tmux = os.environ.get("TMUX")
    if pane and tmux:
        # $TMUX is "socket,pid,session-index"; the socket matters for -S.
        found["tmux_pane"] = pane
        found["tmux_socket"] = tmux.split(",")[0]

    term = os.environ.get("TERM_PROGRAM")
    if term:
        found["term_program"] = term
    return found
