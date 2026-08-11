"""Checks for where the pet is allowed to be.

The overlay needs a display, so the arithmetic that decides placement is
exercised directly against a stand-in rather than a real window. What is being
checked is the reasoning, which is where the bugs were: the sprite is inset
inside a window that reserves room for the bubble, and treating the two as the
same thing is what stopped the pet reaching the top of the screen and what lost
it on a monitor that had gone away.

Plain stdlib, no test runner needed:

    python3 tests/test_geometry.py
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class Area:
    """Stand-in for Gdk.Rectangle."""

    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self.x, self.y, self.width, self.height = x, y, width, height


#: The real layout on a 1920x1080 screen with a GNOME panel, plus a second
#: screen to its right -- the setup the placement bugs were found on.
PRIMARY = Area(66, 32, 1854, 1048)
SECOND = Area(1920, 0, 1920, 1080)

SPRITE_W, SPRITE_H = 122, 132
BUBBLE_SPACE = 86           # room the bubble takes beside the sprite
WINDOW_W = 260
SPRITE_LEFT = (WINDOW_W - SPRITE_W) // 2
EDGE_MARGIN = 12


class Placer:
    """The overlay's placement rules, with the window parts left out."""

    def __init__(self, monitors: list[Area]) -> None:
        self.monitors = monitors
        self.bubble_below = False
        self.sprite_top = BUBBLE_SPACE
        self.pos_x = self.pos_y = 0

    def workarea_for(self, x: int, y: int) -> Area:
        cx, cy = x + SPRITE_W // 2, y + SPRITE_H // 2
        for area in self.monitors:
            if (area.x <= cx < area.x + area.width
                    and area.y <= cy < area.y + area.height):
                return area

        def distance(area: Area) -> float:
            dx = max(area.x - cx, 0, cx - (area.x + area.width))
            dy = max(area.y - cy, 0, cy - (area.y + area.height))
            return math.hypot(dx, dy)

        return min(self.monitors, key=distance)

    def on_screen(self, x: int, y: int) -> bool:
        return any(
            x + SPRITE_W > a.x and x < a.x + a.width
            and y + SPRITE_H > a.y and y < a.y + a.height
            for a in self.monitors
        )

    def span(self) -> tuple[int, int, int, int]:
        return (
            min(a.x for a in self.monitors) + EDGE_MARGIN,
            min(a.y for a in self.monitors),
            max(a.x + a.width for a in self.monitors) - EDGE_MARGIN - SPRITE_W,
            max(a.y + a.height for a in self.monitors) - EDGE_MARGIN - SPRITE_H,
        )

    def place_across(self, x: int, y: int) -> tuple[int, int]:
        """Placement for something crossing between screens, not staying on one."""
        area = self.workarea_for(x, y)
        left, top, right, bottom = self.span()
        x = min(max(x, left), right)
        y = min(max(y, top), bottom)
        self.bubble_below = y - area.y < BUBBLE_SPACE
        self.sprite_top = 0 if self.bubble_below else BUBBLE_SPACE
        self.pos_x, self.pos_y = x - SPRITE_LEFT, y - self.sprite_top
        return x, y

    def place(self, x: int, y: int) -> tuple[int, int]:
        area = self.workarea_for(x, y)
        x = min(max(x, area.x), area.x + area.width - SPRITE_W)
        y = min(max(y, area.y), area.y + area.height - SPRITE_H)
        self.bubble_below = y - area.y < BUBBLE_SPACE
        self.sprite_top = 0 if self.bubble_below else BUBBLE_SPACE
        self.pos_x, self.pos_y = x - SPRITE_LEFT, y - self.sprite_top
        return x, y


def top_checks() -> list[tuple[str, bool]]:
    """The pet must reach the top of the screen, not 86 pixels short of it.

    The window reserves the bubble's room above the sprite, so when the window
    could go no higher the sprite was still a bubble's height down. The bubble
    moves below the sprite instead when there is nothing above.
    """
    results = []
    placer = Placer([PRIMARY])

    _x, y = placer.place(800, PRIMARY.y)  # dragged as high as it will go
    results.append(("sprite reaches the work area top", y == PRIMARY.y))
    results.append(("...with the bubble moved below it", placer.bubble_below))
    results.append(("...and the window not pushed off screen", placer.pos_y >= PRIMARY.y))
    # The old behaviour, stated so a regression is unmistakable.
    results.append(("sprite is no longer stuck below the bubble", y < PRIMARY.y + BUBBLE_SPACE))

    _x, y = placer.place(800, 600)  # back down in open space
    results.append(("bubble returns above when there is room", not placer.bubble_below))
    results.append(("window sits a bubble above the sprite", placer.pos_y == y - BUBBLE_SPACE))

    _x, y = placer.place(800, 5000)  # dragged off the bottom
    results.append(
        ("sprite stays on screen at the bottom",
         y + SPRITE_H <= PRIMARY.y + PRIMARY.height)
    )
    return results


def monitor_checks() -> list[tuple[str, bool]]:
    """Bounds belong to the screen the pet is on, not always the primary one."""
    results = []
    placer = Placer([PRIMARY, SECOND])

    on_second = placer.workarea_for(2500, 500)
    results.append(("a pet on the second screen is judged there", on_second.x == SECOND.x))

    # Walking on the second screen must not be dragged back over the seam.
    x, _y = placer.place(3000, 500)
    results.append(("it may stay on the second screen", x == 3000))

    x, _y = placer.place(3900, 500)  # past the right edge of the second screen
    results.append(
        ("it stops at that screen's edge", x == SECOND.x + SECOND.width - SPRITE_W)
    )

    results.append(("a position on a live screen is kept", placer.on_screen(3000, 500)))
    results.append(("one on no screen at all is rejected", not placer.on_screen(9000, 9000)))
    # The case that stranded the pet: the screen it was on has been unplugged.
    unplugged = Placer([PRIMARY])
    results.append(
        ("a position on an unplugged screen is rejected", not unplugged.on_screen(3000, 500))
    )
    results.append(("...while the primary one is still fine", unplugged.on_screen(800, 500)))
    return results


def errand_checks() -> list[tuple[str, bool]]:
    """A pet called across the seam has to actually get there.

    Reported as the pointer appearing to stop at the join: with the pet on
    the second screen and the pointer moved to the first, the pet behaved as
    though the pointer had stayed where it crossed. Nothing was wrong with
    reading the pointer -- the bounds were. To count as being on the first
    screen the sprite's centre must pass the seam, and the second screen's
    own bounds forbid exactly that, so it walks up to the join and stops.
    """
    results = []

    def walk(placer: Placer, across: bool, start: tuple[int, int],
             pointer: tuple[int, int], seconds: float = 90.0,
             aim_across: bool | None = None):
        """Run the errand arithmetic.

        Returns where it ended, how far left it got, and how long it spent
        pinned against the seam -- which is the symptom, the pet behaving as
        though the pointer had stopped where it crossed.
        """
        speed = 3 * 10 * 2.0        # walk_speed x fps x CALL_PACE, the shipped default
        tick = 0.016
        x, y = start
        at = (float(x), float(y))
        west = x
        elapsed = 0.0
        pinned = 0.0
        while elapsed < seconds:
            target_x, target_y = pointer[0] - SPRITE_W // 2, pointer[1] - SPRITE_H // 2
            if aim_across if aim_across is not None else across:
                left, top, right, bottom = placer.span()
            else:
                # What it used to aim at: the bounds of its own screen, which
                # put the target on the seam and no further.
                own = placer.workarea_for(x, y)
                left, top = own.x, own.y
                right, bottom = own.x + own.width - SPRITE_W, own.y + own.height - SPRITE_H
            target_x = min(max(target_x, left), right)
            target_y = min(max(target_y, top), bottom)
            remaining_x, remaining_y = target_x - x, target_y - y
            distance = math.hypot(remaining_x, remaining_y)
            if distance <= SPRITE_W / 2 + 8:
                break
            step = speed * tick
            if math.hypot(at[0] - x, at[1] - y) > WINDOW_W:
                at = (float(x), float(y))
            at = (at[0] + step * remaining_x / distance, at[1] + step * remaining_y / distance)
            put = placer.place_across if across else placer.place
            x, y = put(int(round(at[0])), int(round(at[1])))
            west = min(west, x)
            if abs(x - SECOND.x) <= 4:
                pinned += tick
            elapsed += tick
        return x, y, west, pinned

    placer = Placer([PRIMARY, SECOND])
    # Deep on the second screen, called to the far side of the first.
    x, _y, west, pinned = walk(placer, True, (3400, 500), (700, 500))
    results.append(("a pet called across the seam arrives", abs(x - (700 - SPRITE_W // 2)) <= 70))
    results.append(("...having crossed onto the first screen", west < SECOND.x))
    results.append((f"...without stalling at the join ({pinned:.1f}s)", pinned < 0.5))

    # And the other way, which always worked -- stated so both are pinned.
    x, _y, _west, _pinned = walk(placer, True, (400, 500), (3000, 500))
    results.append(("and one called the other way arrives too",
                    abs(x - (3000 - SPRITE_W // 2)) <= 70))

    # The behaviour that was reported, kept here so the fix cannot quietly
    # come undone: clamped to its own screen, it stops dead at the join.
    # Aiming at its own screen's bounds: the target lands on the seam, the pet
    # walks to it and stops -- indistinguishable from the pointer having
    # stopped there, which is how it was described.
    halted_x, _y, _west, _pinned = walk(placer, False, (3400, 500), (700, 500), seconds=30.0)
    results.append(("aimed at its own screen it halts on the seam",
                    abs(halted_x - SECOND.x) <= SPRITE_W))

    # And placement alone, aiming correctly: it crosses, but only after
    # grinding against the join for about a second.
    _x, _y, _west, stalled = walk(placer, False, (3400, 500), (700, 500),
                                  seconds=30.0, aim_across=True)
    results.append((f"clamped to one screen it stalls at the join ({stalled:.1f}s)",
                    stalled > 0.8))

    # The union has to reach both screens, or the target is clamped away
    # before the walk even starts.
    left, _top, right, _bottom = placer.span()
    results.append(("the crossing bounds span both screens",
                    left < SECOND.x and right > SECOND.x))
    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("top edge", top_checks()), ("monitors", monitor_checks()),
                            ("errands", errand_checks())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
