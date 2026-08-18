"""Checks for deciding when the pointer's position is worth believing.

The fault this guards against is silent in both directions, which is what
makes it worth pinning. Believe a frozen position and the pet walks to a spot
the pointer left. Disbelieve a good one and the pet stops answering at all,
with nothing on screen to say why.

Plain stdlib, no test runner needed:

    python3 tests/test_pointer.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import pointer  # noqa: E402


class Session:
    """Run a check as though on a given session type, with a given answer."""

    def __init__(self, session_type: str, child: int | None,
                 shell: tuple[int, int] | None = None) -> None:
        self.session_type = session_type
        self.child = child
        #: What the shell bridge answers, or None when it is not installed.
        self.shell = shell

    def __enter__(self):
        self.was = os.environ.get("XDG_SESSION_TYPE")
        self.real_query = pointer._query_child
        self.real_shell = pointer.from_shell
        self.real_live = pointer.from_shell_live
        os.environ["XDG_SESSION_TYPE"] = self.session_type
        pointer._query_child = lambda: self.child
        pointer.from_shell = lambda: self.shell
        # The hot path reads the bridge without blocking; in a test there is no
        # main loop to deliver an async reply, so it is stubbed to the same
        # answer the synchronous one would give.
        pointer.from_shell_live = lambda: self.shell
        # One reading is cached and shared between the gesture poll and the
        # walk loop, so a test that did not clear it would be checking the
        # previous case's answer.
        pointer.forget()
        return self

    def __exit__(self, *_exc) -> None:
        pointer._query_child = self.real_query
        pointer.from_shell = self.real_shell
        pointer.from_shell_live = self.real_live
        if self.was is None:
            os.environ.pop("XDG_SESSION_TYPE", None)
        else:
            os.environ["XDG_SESSION_TYPE"] = self.was


def wayland_checks() -> list[tuple[str, bool]]:
    results = []

    # The measured behaviour: a window under the pointer means X11 is being
    # kept up to date; nobody under it means it stopped being told.
    with Session("wayland", 8400340):
        results.append(("over an X11 window the position is believed", pointer.visible()))
    with Session("wayland", 0):
        results.append(("over a Wayland window it is not", not pointer.visible()))
        results.append(("...and doctor says so", "invisible" in (pointer.explain() or "")))

    # Erring towards believing it. A summons missed now and again is a much
    # smaller fault than a pet that never answers because this went wrong,
    # and there is no way for the user to tell the second from a bug.
    with Session("wayland", None):
        results.append(("with X11 unreachable it believes the position anyway",
                        pointer.visible()))
        results.append(("...while saying it could not check",
                        "cannot ask" in (pointer.explain() or "")))
    return results


def x11_checks() -> list[tuple[str, bool]]:
    """On X11 there is nothing to disbelieve, and the same answer means something else."""
    results = []

    # Nobody under the pointer on X11 means it is over the desktop
    # background, where the position is perfectly good. Treating that the
    # Wayland way would stop the pet answering anywhere but over a window.
    with Session("x11", 0):
        results.append(("on X11 an empty answer is not a warning", pointer.visible()))
        results.append(("...and doctor stays quiet", pointer.explain() is None))
    with Session("x11", 8400340):
        results.append(("on X11 a window is fine too", pointer.visible()))

    # An unset session type is not Wayland either -- a bare X server, or a
    # session that never exported it. Same reasoning.
    with Session("", 0):
        results.append(("an unknown session type is left alone", pointer.visible()))
        results.append(("...and is not called wayland", not pointer.under_wayland()))
    with Session("wayland", 0):
        results.append(("wayland is recognised by name", pointer.under_wayland()))
    return results


def fallback_checks() -> list[tuple[str, bool]]:
    """Which source answers, and what happens when neither can.

    X11 first when it is keeping up: it is free, and asking the compositor
    twenty times a second for something already to hand is work it should
    not be doing. The bridge only for the case X11 cannot cover.
    """
    results = []
    x11_says = (100, 200)

    def raw():
        return x11_says

    with Session("wayland", 8400340, shell=(900, 900)):
        results.append(("while X11 keeps up, X11 answers",
                        pointer.trusted_position(raw) == x11_says))
    with Session("wayland", 0, shell=(900, 900)):
        results.append(("once it cannot, the shell answers",
                        pointer.trusted_position(raw) == (900, 900)))
        results.append(("...and doctor stops warning", pointer.explain() is None))
    with Session("wayland", 0, shell=None):
        results.append(("with neither, nobody answers",
                        pointer.trusted_position(raw) is None))
        results.append(("...which is not the frozen position",
                        pointer.trusted_position(raw) != x11_says))

    # On X11 the bridge is never consulted, installed or not.
    with Session("x11", 0, shell=(900, 900)):
        results.append(("on X11 the bridge is not consulted",
                        pointer.trusted_position(raw) == x11_says))
    return results


def sharing_checks() -> list[tuple[str, bool]]:
    """One reading serves both callers, and repeats say so.

    The gesture poll wants the pointer every 50ms and the walk loop sixty
    times a second, and on the bridge path every reading is a round trip into
    the compositor. Asking for each was reported twice over: a circle drawn
    over a Wayland window going unrecognised, and a pet stopping partway
    through an errand.

    Which makes the `fresh` flag load-bearing rather than decorative --
    whether the pointer has settled is judged from consecutive readings, and
    a reused one would say it had stopped moving when it had not.
    """
    results = []
    asked = []

    def raw():
        asked.append(1)
        return (100 + 10 * len(asked), 200)

    with Session("wayland", 8400340):
        first, fresh_first = pointer.sample(raw)
        second, fresh_second = pointer.sample(raw)
        results.append(("the first reading is taken", fresh_first))
        results.append(("...and the second is the same one reused", not fresh_second))
        results.append(("...with the same answer", first == second))
        results.append((f"...having asked once, not twice ({len(asked)}x)", len(asked) == 1))

    with Session("wayland", 8400340):
        results.append(("clearing it makes the next ask go and look",
                        pointer.sample(raw)[1]))

    # A reading nobody can vouch for is not cached and repeated -- that would
    # be the frozen coordinate this module exists to refuse, dressed up as a
    # fresh one.
    with Session("wayland", 0, shell=None):
        results.append(("nothing is cached when nobody can say",
                        pointer.sample(raw) == (None, False)))

    results.append(("the reading is short-lived", 0 < pointer.SAMPLE_SECONDS <= 0.05))
    # The walk loop runs every 16ms and cannot afford to wait on the shell.
    results.append(("the bridge is not waited on for long",
                    pointer.BRIDGE_TIMEOUT_MS <= 80))
    return results


def async_checks() -> list[tuple[str, bool]]:
    """The hot-path read never blocks, and rides out a brief compositor stall.

    The bug it fixes was load-shaped: the bridge runs inside gnome-shell's own
    main loop, so a heavy web page made the synchronous read time out and
    return None -- freezing the walk target and dropping gesture samples, but
    only on a busy page, which is why it was intermittent and site-specific.
    """
    import time

    results = []
    real_pump = pointer._pump_async
    try:
        pointer._pump_async = lambda: None  # no real D-Bus in a test

        # A recent answer is used as-is; nothing blocks.
        pointer._async_pos, pointer._async_at = (321, 654), time.monotonic()
        results.append(("a fresh async answer is returned",
                        pointer.from_shell_live() == (321, 654)))

        # An answer older than the stale window is not walked toward.
        pointer._async_at = time.monotonic() - (pointer.ASYNC_STALE_SECONDS + 0.1)
        results.append(("a stale async answer is refused",
                        pointer.from_shell_live() is None))

        # Never having heard back is None, not a crash.
        pointer._async_pos, pointer._async_at = None, 0.0
        results.append(("no answer yet is None", pointer.from_shell_live() is None))

        # The reply handler stores what the shell sent.
        class Reply:
            @staticmethod
            def unpack():
                return (12, 34)

        class Proxy:
            @staticmethod
            def call_finish(_res):
                return Reply()

        pointer._async_inflight = True
        pointer._on_async_reply(Proxy(), object(), None)
        results.append(("a reply is stored", pointer._async_pos == (12, 34)))
        results.append(("...and clears the in-flight flag",
                        pointer._async_inflight is False))

        # The stale window is a few frames, not a marathon.
        results.append(("the stale window is short",
                        0.1 <= pointer.ASYNC_STALE_SECONDS <= 0.6))
    finally:
        pointer._pump_async = real_pump
        pointer._async_pos, pointer._async_at, pointer._async_inflight = None, 0.0, False
    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("wayland", wayland_checks()), ("x11", x11_checks()),
                            ("fallback", fallback_checks()), ("sharing", sharing_checks()),
                            ("async", async_checks())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
