"""Whether X11 can still see where the pointer is.

The overlay runs under XWayland on purpose -- a Wayland-native window cannot
be put at a chosen place, kept above everything, and refused focus, which is
the whole of what an overlay is. The price is paid here: XWayland is told
where the pointer is only while the pointer is over one of *its* windows.
Move onto a Wayland-native window and the position stops updating, frozen at
wherever it was when it left.

Measured on a GNOME 46 Wayland session, driving the real pointer through the
compositor rather than XTest (an XTest warp goes through XWayland, so
XWayland necessarily knows about it, which makes it useless for this):

      pointer moved to      X11 reports
      3167 -> 2367          keeps up exactly
      onto the next screen  frozen at 1967
      back again            keeps up again

That screen was covered by a Wayland-native browser, and the one it kept up
on by a terminal running under XWayland. So a summons drawn over the
terminal was recognised and the same circle drawn over the browser did
nothing whatever, which is not a thing anyone would guess.

There is no fix from inside the process. GNOME 46 has no portal for reading
the pointer (GlobalShortcuts arrived later), `org.gnome.Shell.Eval` is
locked, and the remaining route -- a screencast session for its cursor
metadata -- means a permission dialog and a screen-sharing indicator for the
lifetime of a desktop pet, which is not a trade worth making.

What can be done is to know. X11 says so plainly: asked who is under the
pointer it names a window while it is keeping up, and answers nobody once it
is not. That is enough to stop reading stale coordinates as though they were
a gesture, and enough for `doctor` to explain the silence.
"""

from __future__ import annotations

import ctypes
import os

#: Cached so the poll does not reopen a display connection every 50ms, and so
#: that a machine without libX11 pays for the failure once.
_xlib: ctypes.CDLL | None = None
_display: int | None = None
_root: int | None = None
_broken = False


def under_wayland() -> bool:
    """Whether the pointer can go somewhere X11 cannot follow.

    Only on Wayland. On a real X11 session nothing is invisible, and the
    same "nobody is under the pointer" answer means only that it is over the
    desktop background -- where the position is perfectly good.
    """
    return os.environ.get("XDG_SESSION_TYPE", "") == "wayland"


def _connect() -> bool:
    global _xlib, _display, _root, _broken
    if _broken:
        return False
    if _display is not None:
        return True
    try:
        _xlib = ctypes.CDLL("libX11.so.6")
        _xlib.XOpenDisplay.restype = ctypes.c_void_p
        _xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        _xlib.XDefaultRootWindow.restype = ctypes.c_ulong
        _xlib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        _xlib.XQueryPointer.argtypes = (
            [ctypes.c_void_p, ctypes.c_ulong]
            + [ctypes.POINTER(ctypes.c_ulong)] * 2
            + [ctypes.POINTER(ctypes.c_int)] * 4
            + [ctypes.POINTER(ctypes.c_uint)]
        )
        display = _xlib.XOpenDisplay(None)
        if not display:
            raise OSError("no display")
        _display = display
        _root = _xlib.XDefaultRootWindow(display)
    except (OSError, AttributeError):
        # No libX11, or no display to open. Never ask again: this is on the
        # gesture poll, and a failing lookup every 50ms is worse than not
        # knowing.
        _broken = True
        return False
    return True


def _query_child() -> int | None:
    """Which X11 window is under the pointer; None if X11 cannot be asked.

    Kept apart from the decision so the decision can be tested: the answer
    comes out of libX11 and there is no arranging it from a test.
    """
    if not _connect():
        return None
    assert _xlib is not None and _display is not None and _root is not None
    root_ret, child = ctypes.c_ulong(), ctypes.c_ulong()
    root_x, root_y, win_x, win_y = (ctypes.c_int() for _ in range(4))
    mask = ctypes.c_uint()
    try:
        _xlib.XQueryPointer(
            _display, _root,
            ctypes.byref(root_ret), ctypes.byref(child),
            ctypes.byref(root_x), ctypes.byref(root_y),
            ctypes.byref(win_x), ctypes.byref(win_y), ctypes.byref(mask),
        )
    except OSError:
        return None
    return child.value


def visible() -> bool:
    """Whether the pointer's position can be trusted right now.

    True when X11 names a window under the pointer, and on anything that is
    not a Wayland session. Errs towards True: a summons that is occasionally
    missed is a smaller fault than a pet that stops answering because this
    went wrong.
    """
    if not under_wayland():
        return True
    child = _query_child()
    return True if child is None else child != 0


def explain() -> str | None:
    """One line for `doctor`, or None when there is nothing to warn about."""
    if not under_wayland():
        return None
    if _query_child() is None:
        return "cannot ask X11 where the pointer is; calling may not work"
    where = "over a window it can see" if visible() else "over a Wayland window, invisible to it"
    return (
        f"the pointer is {where}. On Wayland the pet can only be called from "
        f"over an X11/XWayland window -- a circle drawn over a Wayland-native "
        f"one is never seen."
    )
