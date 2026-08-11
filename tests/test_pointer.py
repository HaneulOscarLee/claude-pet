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
        os.environ["XDG_SESSION_TYPE"] = self.session_type
        pointer._query_child = lambda: self.child
        pointer.from_shell = lambda: self.shell
        return self

    def __exit__(self, *_exc) -> None:
        pointer._query_child = self.real_query
        pointer.from_shell = self.real_shell
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


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("wayland", wayland_checks()), ("x11", x11_checks()),
                            ("fallback", fallback_checks())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
