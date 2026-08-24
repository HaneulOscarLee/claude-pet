"""Checks for throwing the pet.

A throw is the pet's *position* moving, which is the only kind of motion this
project can invent -- a sprite pack ships nine fixed rows and a fall is not one
of them. So the whole feature is arithmetic, and arithmetic can be tried
against the awkward cases without a display: a throw aimed off the screen, one
started in a corner, one too gentle to have been a throw at all.

Plain stdlib, no test runner needed:

    python3 tests/test_motion.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import motion  # noqa: E402

#: left, top, right, bottom, as the overlay passes them.
BOUNDS = (66, 32, 1798, 936)


def settle(throw: motion.Throw, x: float, y: float, seconds: float = 10.0):
    """Run a throw to a standstill; returns where it stopped and how long it took."""
    elapsed = 0.0
    while throw.moving and elapsed < seconds:
        x, y = throw.step(x, y, BOUNDS, 0.05)
        elapsed += 0.05
    return x, y, elapsed


def flick_checks() -> list[tuple[str, bool]]:
    """Telling a throw from putting the pet down."""
    results = []

    # A slow drag, however far it goes, is a placement.
    flick = motion.Flick()
    for step in range(20):
        flick.record(500 + step * 5, 400, step * 0.1)
    results.append(("a slow drag is not a throw", flick.release() is None))

    # A flick at the end is, even if the drag before it was slow.
    flick = motion.Flick()
    for step in range(10):
        flick.record(500 + step * 5, 400, step * 0.1)
    for step in range(6):
        flick.record(560 + step * 140, 400, 1.0 + step * 0.02)
    results.append(("a flick at the end is a throw", flick.release() is not None))

    # Reported as too eager: an ordinary drag was being thrown. Anything up to
    # a brisk placement has to stay a placement, since getting this wrong moves
    # the pet somewhere the person did not put it.
    def at(speed: float, diagonal: bool = False) -> motion.Throw | None:
        moving = motion.Flick()
        for step in range(8):
            travelled = speed * (step * 0.02)
            if diagonal:
                moving.record(500 + travelled * 0.707, 400 + travelled * 0.707, step * 0.02)
            else:
                moving.record(500 + travelled, 400, step * 0.02)
        return moving.release()

    # Raised twice after being reported too eager. Plenty of people release
    # while still moving rather than stopping first, so everything up to a
    # fast drag has to stay a placement.
    for speed in (300, 1200, 2000, 3500):
        results.append((f"a drag at {speed} px/s is a placement", at(speed) is None))
    for speed in (5500, 9000):
        results.append((f"a flick at {speed} px/s is a throw", at(speed) is not None))

    # Speed measured straight-line, not as the sum of the parts: adding them
    # made a diagonal drag read half again as fast as it was, so corner-aimed
    # throws fired on gentler flicks than sideways ones.
    results.append(("a diagonal drag is judged at its true speed", at(3500, diagonal=True) is None))

    # The number the debug line reports, which is how the threshold gets
    # argued about with measurements instead of opinions.
    measured = motion.Flick()
    for step in range(8):
        measured.record(500 + 2000 * (step * 0.02), 400, step * 0.02)
    results.append(("release speed is reported", abs(measured.speed() - 2000) < 50))
    results.append(("...and is 0 with nothing to measure", motion.Flick().speed() == 0.0))

    # Fast but going nowhere -- a shake at the moment of release.
    shake = motion.Flick()
    for step in range(8):
        shake.record(500 + (step % 2) * 20, 400, step * 0.01)
    results.append(("a shake that covers no ground is not a throw", shake.release() is None))

    # Only the tail counts, so the slow part cannot dilute it. Asserted on
    # which samples survived rather than how many, the count being an artefact
    # of how the test happens to move the pointer.
    results.append(("...and the slow part before it is dropped",
                    all(at >= 1.0 for at, _x, _y in flick.samples)))

    # Nothing to measure.
    results.append(("a click with no movement is not a throw", motion.Flick().release() is None))
    flick = motion.Flick()
    flick.record(500, 400, 0.0)
    results.append(("a single sample is not a throw", flick.release() is None))

    # Cleared between drags, or the next one inherits this one's speed.
    flick.clear()
    results.append(("clearing forgets the drag", flick.release() is None))
    return results


def throw_checks() -> list[tuple[str, bool]]:
    results = []
    left, top, right, bottom = BOUNDS

    # It has to stop, and reasonably soon -- a pet skating about for five
    # seconds stops being funny.
    x, y, elapsed = settle(motion.Throw(3000, 0), 900, 500)
    results.append((f"a hard throw settles ({elapsed:.1f}s)", elapsed < 4.0))

    # And it must never leave the screen, which is the failure that would
    # matter: a pet thrown out of reach cannot be clicked to bring back.
    for velocity in ((6000, 0), (-6000, 0), (0, 6000), (0, -6000), (5000, 5000)):
        x, y, _ = settle(motion.Throw(*velocity), 900, 500)
        inside = left <= x <= right and top <= y <= bottom
        results.append((f"thrown at {velocity} it stays on screen", inside))

    # Thrown from a corner, at the wall.
    x, y, _ = settle(motion.Throw(-4000, -4000), left, top)
    results.append(("thrown into a corner it stays inside",
                    left <= x <= right and top <= y <= bottom))

    # A bounce gives back well under half, so it cannot ricochet forever.
    throw = motion.Throw(2000, 0)
    throw.step(right, 500, BOUNDS, 0.05)
    results.append(("a bounce reverses and loses speed",
                    throw.velocity_x < 0 and abs(throw.velocity_x) < 2000 * 0.5))

    # The animation rate is a user setting; a throw must not travel further on
    # a faster pet.
    far = settle(motion.Throw(2500, 0), 900, 500)[0]
    slow = motion.Throw(2500, 0)
    x, y = 900.0, 500.0
    for _ in range(50):
        if not slow.moving:
            break
        x, y = slow.step(x, y, BOUNDS, 0.2)
    results.append(("distance does not depend on frame rate", abs(far - x) < 60))

    results.append(("a throw below the settle speed is already over",
                    not motion.Throw(5, 5).moving))
    return results


def l_shaped_checks() -> list[tuple[str, bool]]:
    """A throw must bounce off the screens, not off the box around them.

    Reported on three monitors in a "ㄱ": two across the top, one below the
    right-hand pair. The bounding box of the three covers a bottom-left corner
    with no screen behind it, and a rectangle cannot say so -- so a throw aimed
    down-left sailed into the hole and settled there, out of sight.
    """
    MONITORS = ((0, 0, 1920, 1080), (1920, 0, 1920, 1080), (1920, 1080, 1920, 1080))
    EDGE, WIDE, TALL = 12, 122, 132
    span = (EDGE, 0, 3840 - EDGE - WIDE, 2160 - EDGE - TALL)

    def on_screen(x, y):
        return any(x + WIDE > mx and x < mx + mw and y + TALL > my and y < my + mh
                   for mx, my, mw, mh in MONITORS)

    def clamp(x, y):
        best = None
        for mx, my, mw, mh in MONITORS:
            left, top = mx + EDGE, my
            right = max(left, mx + mw - EDGE - WIDE)
            bottom = max(top, my + mh - EDGE - TALL)
            near_x, near_y = min(max(x, left), right), min(max(y, top), bottom)
            distance = (near_x - x) ** 2 + (near_y - y) ** 2
            if best is None or distance < best[0]:
                best = (distance, near_x, near_y)
        return best[1], best[2]

    def fly(velocity, start, use_clamp):
        throw = motion.Throw(*velocity)
        x, y = float(start[0]), float(start[1])
        strayed = False
        for _ in range(200):
            if not throw.moving:
                break
            x, y = throw.step(x, y, span, 0.05,
                              **({"clamp": clamp} if use_clamp else {}))
            if not on_screen(x, y):
                strayed = True
        return (x, y), strayed

    results = []
    # The reported throw: hurled down and to the left, straight at the hole.
    (x, y), strayed = fly((-3000, 2600), (1900, 900), use_clamp=True)
    results.append((f"a throw at the empty corner stays on a screen ({int(x)},{int(y)})",
                    on_screen(x, y)))
    results.append(("...and never crosses it on the way", not strayed))

    # The same throw without the clamp is the bug, stated so the fix cannot
    # quietly come undone.
    (bx, by), _ = fly((-3000, 2600), (1900, 900), use_clamp=False)
    results.append((f"...where the plain rectangle loses it ({int(bx)},{int(by)})",
                    not on_screen(bx, by)))

    # Every direction, from each screen, since only one throw was reported.
    for velocity in ((-6000, 6000), (-4000, 4000), (0, 6000), (-6000, 0), (5000, 5000)):
        for start in ((1900, 900), (100, 100), (2500, 1600)):
            (fx, fy), stray = fly(velocity, start, use_clamp=True)
            results.append((f"thrown {velocity} from {start} it stays on screen",
                            on_screen(fx, fy) and not stray))

    # And it still settles rather than skating about forever.
    throw = motion.Throw(-6000, 6000)
    x, y, ticks = 1900.0, 900.0, 0
    while throw.moving and ticks < 200:
        x, y = throw.step(x, y, span, 0.05, clamp=clamp)
        ticks += 1
    results.append((f"a bounced throw still comes to rest ({ticks * 0.05:.1f}s)",
                    not throw.moving))
    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("flick", flick_checks()), ("flight", throw_checks()),
                            ("L-shaped", l_shaped_checks())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
