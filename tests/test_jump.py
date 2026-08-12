"""Checks for picking the window a session is actually in.

The fault this guards against is quiet and infuriating: the pet says a session
needs you, you click it, and a *different* terminal window comes forward. It
happens only with a terminal that serves several windows from one process, so
it is invisible until someone opens a second window and then constant.

`wmctrl` is stubbed rather than run, since what is being checked is the
choice, not the raising.

Plain stdlib, no test runner needed:

    python3 tests/test_jump.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import jump  # noqa: E402

#: Two windows of one Terminator process, exactly as `wmctrl -lp` prints them,
#: plus an unrelated window of another application.
LISTING = (
    "0x00e00007 -1 877340 thinkpad ⠐ Codex 앱의 pets 기능 확인\n"
    "0x00ed6461  0 877340 thinkpad haneullee@thinkpad: ~\n"
    "0x01000003 -1 998877 thinkpad claude-pet\n"
)

TERMINAL_PIDS = [4080359, 878200, 877516, 877340, 876039]


class Listing:
    """Answer `wmctrl -lp` from a string, and pretend it is installed."""

    def __init__(self, text: str = LISTING) -> None:
        self.text = text

    def __enter__(self):
        self.real_run = jump.subprocess.run
        self.real_which = jump.shutil.which

        class Result:
            def __init__(self, stdout: str) -> None:
                self.stdout = stdout
                self.returncode = 0

        jump.subprocess.run = lambda argv, **_kw: Result(
            self.text if argv[:2] == ["wmctrl", "-lp"] else ""
        )
        jump.shutil.which = lambda name: "/usr/bin/" + name if name == "wmctrl" else None
        return self

    def __exit__(self, *_exc) -> None:
        jump.subprocess.run = self.real_run
        jump.shutil.which = self.real_which


class Terminal:
    """Stand in for the terminal answering "which window is this terminal in?"."""

    def __init__(self, answers: dict[str, str]) -> None:
        self.answers = answers
        self.asked: list[str] = []

    def __enter__(self):
        self.real = jump._terminal_window_title

        def ask(locator):
            uuid = locator.get("terminal_uuid")
            self.asked.append(uuid)
            return self.answers.get(uuid)

        jump._terminal_window_title = ask
        return self

    def __exit__(self, *_exc) -> None:
        jump._terminal_window_title = self.real


def window_checks() -> list[tuple[str, bool]]:
    results = []

    with Listing():
        # No title to go on: the first window owned by the process. Right for a
        # terminal that runs one process per window, and the old behaviour.
        results.append(("with nothing to go on, the first owned window",
                        jump._x11_window_for(TERMINAL_PIDS) == "0x00e00007"))

        # With one, the window has to match it too. This is the whole fix: the
        # second window of the same process was unreachable, so a session
        # waiting in it raised its sibling instead.
        results.append(("a title picks the first window",
                        jump._x11_window_for(TERMINAL_PIDS, "⠐ Codex 앱의 pets 기능 확인")
                        == "0x00e00007"))
        results.append(("...and picks the second, which used to be unreachable",
                        jump._x11_window_for(TERMINAL_PIDS, "haneullee@thinkpad: ~")
                        == "0x00ed6461"))

        # A title that matches nothing falls back rather than giving up: the
        # window may have been retitled between the ask and the look, and the
        # sibling is a better answer than no answer.
        results.append(("a title matching nothing still raises something",
                        jump._x11_window_for(TERMINAL_PIDS, "a window since renamed")
                        == "0x00e00007"))

        # Another application's window is never a candidate, titled or not.
        results.append(("a window owned by nothing in the chain is ignored",
                        jump._x11_window_for(TERMINAL_PIDS, "claude-pet") == "0x00e00007"))
        results.append(("...and with no owned window at all, nothing",
                        jump._x11_window_for([424242], "claude-pet") is None))
    return results


def locator_checks() -> list[tuple[str, bool]]:
    """The uuid has to travel from the shell's environment to the jump."""
    import os

    results = []
    from claude_pet import locate

    was = {name: os.environ.get(name) for name in
           ("TERMINATOR_UUID", "TERMINATOR_DBUS_NAME", "TERMINATOR_DBUS_PATH")}
    try:
        os.environ.update({
            "TERMINATOR_UUID": "urn:uuid:abc",
            "TERMINATOR_DBUS_NAME": "net.tenshu.Terminator2deadbeef",
            "TERMINATOR_DBUS_PATH": "/net/tenshu/Terminator2",
        })
        found = locate.locator()
        results.append(("the terminal's uuid is recorded",
                        found.get("terminal_uuid") == "urn:uuid:abc"))
        results.append(("...with where to ask about it",
                        found.get("terminal_path") == "/net/tenshu/Terminator2"))

        # Half of it is no use: without a bus to ask, the uuid names nothing.
        os.environ.pop("TERMINATOR_DBUS_NAME")
        found = locate.locator()
        results.append(("a uuid with nowhere to ask records no bus",
                        "terminal_bus" not in found))

        # And the ordinary case: a terminal that says none of this.
        for name in was:
            os.environ.pop(name, None)
        found = locate.locator()
        results.append(("a terminal that says nothing records nothing",
                        "terminal_uuid" not in found))
    finally:
        for name, value in was.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return results


def end_to_end_checks() -> list[tuple[str, bool]]:
    """Two sessions in two windows of one process must land in different ones."""
    results = []
    first = {"pids": TERMINAL_PIDS, "terminal_uuid": "urn:uuid:one",
             "terminal_bus": "net.tenshu.X", "terminal_path": "/net/tenshu/X"}
    second = dict(first, terminal_uuid="urn:uuid:two")
    titles = {"urn:uuid:one": "⠐ Codex 앱의 pets 기능 확인",
              "urn:uuid:two": "haneullee@thinkpad: ~"}

    with Listing(), Terminal(titles) as terminal:
        chosen = [
            jump._x11_window_for(
                [pid for pid in locator["pids"]], jump._terminal_window_title(locator)
            )
            for locator in (first, second)
        ]
        results.append((f"two sessions, two windows ({', '.join(chosen)})",
                        chosen == ["0x00e00007", "0x00ed6461"]))
        results.append(("...and the terminal was asked about each",
                        terminal.asked == ["urn:uuid:one", "urn:uuid:two"]))

    # A terminal that answers nothing leaves the old behaviour exactly as it
    # was, which is what every other terminal gets.
    with Listing(), Terminal({}):
        results.append(("a silent terminal falls back to the first window",
                        jump._x11_window_for(TERMINAL_PIDS,
                                             jump._terminal_window_title(first))
                        == "0x00e00007"))
    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("windows", window_checks()), ("locator", locator_checks()),
                            ("end to end", end_to_end_checks())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
