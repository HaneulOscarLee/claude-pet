"""Checks for the Claude Desktop side of the pet.

Nothing here needs the app installed, a display or a session bus: the parts
that talk to those are isolated behind `main_pid`, `_comm_of` and GDBus, and
what is worth testing is the decisions made around them.

Plain stdlib, no test runner needed:

    python3 tests/test_desktop.py
"""

import contextlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import desktop, jump, state  # noqa: E402

NOW = time.time()


@contextlib.contextmanager
def procs(table: dict[int, str]):
    """Pin /proc: pid -> comm, so these run the same everywhere."""
    original_desktop = desktop._comm_of
    original_state = state._comm_of
    desktop._comm_of = lambda pid: table.get(int(pid), "")
    state._comm_of = lambda pid: table.get(int(pid), "")
    try:
        yield
    finally:
        desktop._comm_of = original_desktop
        state._comm_of = original_state


def origin_checks() -> list[tuple[str, bool]]:
    """Which side a Claude Code session came from, decided by its ancestry."""
    results = []
    table = {100: "claude", 200: "bash", 300: "terminator", 400: "claude-desktop"}
    with procs(table):
        results.append(
            ("terminal ancestry -> terminal",
             desktop.origin_of([200, 300]) == desktop.ORIGIN_TERMINAL)
        )
        results.append(
            ("app ancestry -> desktop",
             desktop.origin_of([400]) == desktop.ORIGIN_DESKTOP)
        )
        # The app spawns the binary through a helper, so the marker is rarely
        # the immediate parent.
        results.append(
            ("app ancestry deeper in the chain -> desktop",
             desktop.origin_of([200, 400]) == desktop.ORIGIN_DESKTOP)
        )
        results.append(("empty ancestry -> terminal", desktop.origin_of([]) == "terminal"))
    return results


def liveness_checks() -> list[tuple[str, bool]]:
    """The app's entry is watched by pid like any other, but by a different name."""
    results = []
    table = {14067: "claude-desktop", 900: "claude"}
    with procs(table):
        app = {
            "state": "review", "ts": NOW,
            "locator": {"claude_pid": 14067, "comm": "claude-desktop",
                        "origin": desktop.ORIGIN_DESKTOP},
        }
        results.append(("running app is live", state.is_alive(app, NOW)))

        closed = {
            "state": "review", "ts": NOW,
            "locator": {"claude_pid": 14068, "comm": "claude-desktop"},
        }
        results.append(("closed app is not live", not state.is_alive(closed, NOW)))

        # A locator with no `comm` still means a Claude Code session, so the
        # app's pid must not satisfy one.
        mismatched = {"state": "running", "ts": NOW, "locator": {"claude_pid": 14067}}
        results.append(
            ("app pid does not pass as a claude session", not state.is_alive(mismatched, NOW))
        )

        session = {"state": "running", "ts": NOW, "locator": {"claude_pid": 900}}
        results.append(("ordinary session unaffected", state.is_alive(session, NOW)))
    return results


def dwell_checks() -> list[tuple[str, bool]]:
    """A notification is an edge, so what it sets has to expire by itself.

    The app announces that a reply arrived and never says it was read. Left on
    the shared dwell table `waiting` holds forever by design -- correct for a
    Claude Code session that keeps re-reporting it, a pet stuck on "needs you"
    for anything derived from a notification.
    """
    results = []

    def entry(name: str, age: float, dwell: float | None) -> dict:
        session = {"state": name, "ts": NOW - age, "detail": "Claude"}
        if dwell is not None:
            session["dwell"] = dwell
        return session

    # Nothing derived from a notification is `waiting` any more, but the
    # override that makes one expire is still what protects the pet if that
    # ever changes.
    results.append(
        ("a session-carried dwell expires waiting",
         state.effective_state(entry("waiting", 90, 60.0), NOW) == "idle")
    )
    results.append(
        ("...and holds until then",
         state.effective_state(entry("waiting", 30, 60.0), NOW) == "waiting")
    )
    # The rule it overrides, unchanged for real sessions.
    results.append(
        ("a real session's waiting still never expires",
         state.effective_state(entry("waiting", 10800, None), NOW) == "waiting")
    )
    results.append(
        ("notification review expires on schedule",
         state.effective_state(entry("review", 25, 20.0), NOW) == "idle")
    )
    results.append(
        ("every classified state has a dwell",
         all(name in desktop.NOTIFY_DWELL_SECONDS for name in ("review", "waiting")))
    )

    # Keeping a long-lived entry alive must not restart its dwell -- the bug
    # that resurrected an hour-old "needs you" every few minutes.
    stale = {"state": "waiting", "ts": NOW - 3600, "seen": NOW, "dwell": 60.0}
    results.append(("a touched entry does not replay", state.effective_state(stale, NOW) == "idle"))

    table = {14067: "claude-desktop"}
    with procs(table):
        stale["locator"] = {"claude_pid": 14067, "comm": "claude-desktop"}
        results.append(("...but is still live", state.is_alive(stale, NOW)))

        # And `seen` has to actually keep it alive, or the entry would be
        # pruned once its report aged past the TTL.
        old = {
            "state": "idle", "ts": NOW - state.SESSION_TTL_SECONDS - 60, "seen": NOW,
            "locator": {"claude_pid": 14067, "comm": "claude-desktop"},
        }
        results.append(("seen keeps an old report alive", state.is_alive(old, NOW)))
    return results


def notification_checks() -> list[tuple[str, bool]]:
    results = [
        ("reply -> done", desktop.classify("Claude", "Your response is ready") == "review"),
        # Reading the prose for "permission"-ish words promoted ordinary
        # notices to the highest-priority state there is. `확인` is the label
        # on half the OK buttons in Korean, so a plain "your reply is ready"
        # became a pet demanding attention nobody had asked for.
        ("korean 확인 is not a permission ask",
         desktop.classify("응답을 확인하세요", "") == "review"),
        ("english permission wording is not either",
         desktop.classify("Claude", "Claude needs your permission") == "review"),
        ("nothing a notification says produces needs-you",
         all(desktop.classify(text, other) == "review"
             for text in ("승인", "권한", "대기 중", "approve", "confirm", "allow", "")
             for other in ("", "anything at all"))),
        ("app name matches",
         desktop.is_claude_notification("Claude", None)),
        ("desktop-entry hint matches",
         desktop.is_claude_notification("", {"desktop-entry": "com.anthropic.Claude"})),
        # The pet posting its own notification and then reacting to it would
        # latch `review` on forever.
        ("our own notifications ignored",
         not desktop.is_claude_notification("claude-pet", None)),
        ("other apps ignored", not desktop.is_claude_notification("Slack", {})),
    ]

    # GNOME's notification service is a relay: it forwards the call on to the
    # real daemon, so a monitor sees every notification twice.
    watcher = desktop.NotifyWatcher(lambda *_: None)
    first = watcher._is_echo("Claude", "Claude", "done")
    echo = watcher._is_echo("Claude", "Claude", "done")
    different = watcher._is_echo("Claude", "Claude", "something else")
    results.append(("first notification is not an echo", not first))
    results.append(("relayed copy is an echo", echo))
    results.append(("different text is not an echo", not different))
    return results


def tmux_window_checks() -> list[tuple[str, bool]]:
    """A tmux session needs the pane selected *and* the window raised.

    They are separate jobs and tmux only does the first: it moves its own pane
    without touching window stacking, so on its own it lands you on the right
    pane of a window that is still behind everything else -- and says it took
    you there.

    Finding that window is its own problem. Inside tmux the recorded ancestry
    reads `bash -> tmux: server -> systemd`; the server is detached from every
    terminal and owns no window, so the terminal is reached through the tmux
    *client* instead.
    """
    results = []
    calls = []
    saved = {n: getattr(jump, n) for n in ("_desktop_jump", "_x11_jump", "_dbus_jump", "_tmux_jump")}

    def stub(name, result):
        def probe(_locator):
            calls.append(name)
            return result
        return probe

    ok = jump.JumpResult(True, "raised the terminal")
    pane = jump.JumpResult(True, "switched to %0")
    locator = {"tmux_pane": "%0", "pids": [1, 2]}
    try:
        jump._desktop_jump = stub("desktop", None)
        jump._dbus_jump = stub("dbus", None)
        jump._x11_jump = stub("x11", ok)
        jump._tmux_jump = stub("tmux", pane)
        result = jump.to_session(locator)
        results.append(("the window route runs for a tmux session", "x11" in calls))
        results.append(("...and so does the pane route", "tmux" in calls))
        results.append(("the window is raised first", calls.index("x11") < calls.index("tmux")))
        results.append(("the pane has the last word", result.message == "switched to %0"))

        calls.clear()
        jump._x11_jump = stub("x11", jump.JumpResult(False, "could not raise the terminal"))
        result = jump.to_session(locator)
        results.append(
            ("a pane switch into a buried window says so", "stayed put" in result.message)
        )

        calls.clear()
        jump._x11_jump = stub("x11", None)
        result = jump.to_session(locator)
        results.append(("tmux alone still works", result.ok and result.message == "switched to %0"))
    finally:
        for name, function in saved.items():
            setattr(jump, name, function)
    return results


def jump_checks() -> list[tuple[str, bool]]:
    """A session inside the app must not be sent down the terminal routes."""
    results = []
    calls = []
    original = desktop.focus
    desktop.focus = lambda: (calls.append(1), (True, "raised Claude Desktop"))[1]
    try:
        result = jump.to_session({"origin": desktop.ORIGIN_DESKTOP, "pids": [1, 2]})
        results.append(("desktop session raises the app", bool(result) and len(calls) == 1))

        # A terminal session must never reach it, even with the app installed.
        result = jump._desktop_jump({"origin": desktop.ORIGIN_TERMINAL, "pids": [1]})
        results.append(("terminal session declines the app route", result is None))
        results.append(("locator with no origin declines", jump._desktop_jump({}) is None))
    finally:
        desktop.focus = original
    return results


def main() -> int:
    failures = 0
    groups = [
        ("origin", origin_checks()),
        ("liveness", liveness_checks()),
        ("dwells", dwell_checks()),
        ("notifications", notification_checks()),
        ("jump", jump_checks()),
        ("tmux windows", tmux_window_checks()),
    ]
    total = 0
    for label, results in groups:
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
