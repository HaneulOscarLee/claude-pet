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


class Tmux:
    """Answer tmux queries from a fixed picture, and record what was run.

    A stand-in rather than a real server: what is under test is which client
    the jump decides to move, and the deciding is all in the query answers.
    """

    def __init__(self, clients: dict[str, str], target_session: str) -> None:
        #: client name -> the session it is attached to.
        self.clients = clients
        self.target_session = target_session
        self.ran: list[list[str]] = []

    def __enter__(self):
        self.real_query = jump._tmux_query
        self.real_run = jump._run
        self.real_which = jump.shutil.which

        def query(base, argv):
            if argv[0] == "list-clients" and "-t" in argv:
                # Clients on the target's own session.
                names = [n for n, s in self.clients.items() if s == self.target_session]
                return "\n".join(names)
            if argv[0] == "list-clients":
                return "\n".join(f"{n}\t{s}" for n, s in self.clients.items())
            if argv[0] == "display-message":
                return self.target_session
            return ""

        def run(argv):
            self.ran.append(argv)
            if argv[1:3] == ["switch-client", "-c"] or "switch-client" in argv:
                # Apply it, so the test can see who ended up where.
                if "-c" in argv:
                    who = argv[argv.index("-c") + 1]
                    self.clients[who] = self.target_session
            return True

        jump._tmux_query = query
        jump._run = run
        jump.shutil.which = lambda name: "/usr/bin/" + name
        return self

    def __exit__(self, *_exc):
        jump._tmux_query = self.real_query
        jump._run = self.real_run
        jump.shutil.which = self.real_which

    def switched(self):
        return [a for a in self.ran if "switch-client" in a]


def tmux_checks() -> list[tuple[str, bool]]:
    """Which client a jump is allowed to move.

    Reported as every session turning into the same session. `switch-client
    -t <pane>` was called with no `-c`, and run from outside tmux there is no
    current client -- so tmux chose one itself, and chose a client watching
    something else. Reproduced on tmux 3.4: a client on `beta` was dragged to
    `alpha` by a jump aimed at a pane in `alpha`, and windows piled onto
    whichever session the pet last pointed at.
    """
    locator = {"tmux_pane": "%0", "tmux_socket": "/tmp/s"}
    results = []

    # Somebody is already on the target's session: select the window and move
    # nobody. This is the case that was hijacking a bystander.
    with Tmux({"a": "target", "b": "other"}, "target") as tmux:
        jump._tmux_jump(locator)
        results.append(("with the session already shown, no client is moved",
                        not tmux.switched()))
        results.append(("...and the bystander stays where it was",
                        tmux.clients == {"a": "target", "b": "other"}))
        results.append(("...the window was still selected",
                        any("select-window" in a for a in tmux.ran)))

    # Nobody on the target session, and every client is the only pair of eyes
    # on its own: moving any of them would take a session away from someone,
    # so nothing is moved.
    with Tmux({"a": "one", "b": "two"}, "target") as tmux:
        jump._tmux_jump(locator)
        results.append(("when every client is a sole viewer, none is taken",
                        not tmux.switched()))
        results.append(("...so no window is hijacked",
                        tmux.clients == {"a": "one", "b": "two"}))

    # Two clients share a session, so one can be lent without anybody losing
    # sight of it.
    with Tmux({"a": "shared", "b": "shared", "c": "elsewhere"}, "target") as tmux:
        jump._tmux_jump(locator)
        moved = tmux.switched()
        results.append((f"a spare client is lent when one can be ({len(moved)})",
                        len(moved) == 1))
        results.append(("...named explicitly, never left to tmux's choice",
                        bool(moved) and "-c" in moved[0]))
        lent = [n for n, s in tmux.clients.items() if s == "target"]
        results.append((f"...exactly one client ends up there ({lent})", len(lent) == 1))
        results.append(("...and the shared session still has a viewer",
                        list(tmux.clients.values()).count("shared") == 1))
        results.append(("...the unrelated client is untouched",
                        tmux.clients["c"] == "elsewhere"))

    # No clients at all: nothing to move, and nothing to crash on.
    with Tmux({}, "target") as tmux:
        jump._tmux_jump(locator)
        results.append(("with no clients attached it just selects", not tmux.switched()))
    return results


def shell_raise_checks() -> list[tuple[str, bool]]:
    """The route that raises a native Wayland terminal via the shell extension.

    An external client cannot raise another application's window on Wayland,
    which is why `fix-terminal` used to wrap the terminal under XWayland -- the
    wrapping that froze it. The compositor can raise anyone, so the extension
    does it, and no terminal needs wrapping. Here the D-Bus call is stubbed;
    what is checked is that the route is tried and its answer respected.
    """
    import types

    results = []
    calls = []

    def fake_bus(answer):
        # A stand-in for the Gio bus whose call_sync returns `answer`, or raises.
        def call_sync(*args, **kwargs):
            calls.append(args)
            if answer is None:
                raise RuntimeError("extension not there")
            return types.SimpleNamespace(unpack=lambda: (answer,))
        return types.SimpleNamespace(call_sync=call_sync)

    real = jump._shell_raise

    def run_with(answer, locator):
        import claude_pet.jump as J
        gi = types.ModuleType("gi"); rep = types.ModuleType("gi.repository")
        class _Var:
            def __init__(self, *a, **k): pass
        Gio = types.SimpleNamespace(
            BusType=types.SimpleNamespace(SESSION=0),
            DBusCallFlags=types.SimpleNamespace(NONE=0),
            bus_get_sync=lambda *_a: fake_bus(answer),
        )
        GLib = types.SimpleNamespace(Variant=lambda *a: None)
        rep.Gio = Gio; rep.GLib = GLib
        import sys
        saved = sys.modules.get("gi"), sys.modules.get("gi.repository")
        sys.modules["gi"] = gi; sys.modules["gi.repository"] = rep
        try:
            return J._shell_raise(locator)
        finally:
            for k, v in (("gi", saved[0]), ("gi.repository", saved[1])):
                if v is None: sys.modules.pop(k, None)
                else: sys.modules[k] = v

    loc = {"pids": [4242]}
    calls.clear()
    r = run_with(True, loc)
    results.append(("a raised window is a successful jump", r is not None and r.ok))
    results.append(("...and the extension was actually called", len(calls) == 1))

    r = run_with(False, loc)
    results.append(("no matching window lets other routes try (None)", r is None))

    r = run_with(None, loc)
    results.append(("no extension there lets other routes try (None)", r is None))

    results.append(("with no pids at all it declines",
                    run_with(True, {"pids": []}) is None))

    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("windows", window_checks()), ("locator", locator_checks()),
                            ("end to end", end_to_end_checks()), ("tmux", tmux_checks()), ("shell-raise", shell_raise_checks())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
