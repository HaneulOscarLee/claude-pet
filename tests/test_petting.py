"""Checks for recognising a pet being stroked.

The whole feature is one judgement call: nothing separates "stroking the pet"
from "moving the pointer across it" except that a stroke turns around. A rule
about that is worth only as much as the cases it has been tried against, so
both halves are pinned here -- what must set it off, and what must not.

Plain stdlib, no test runner needed:

    python3 tests/test_petting.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_pet import petting  # noqa: E402

FAR = petting.STROKE_PIXELS + 4


def rub(stroke: petting.Stroke, sweeps: int, start: float = 100.0, step: float = 0.1) -> int:
    """Sweep back and forth over the pet; returns how often it reacted."""
    reacted = 0
    x, now = 500, start
    for index in range(sweeps):
        x += FAR * (1 if index % 2 == 0 else -1)
        now += step
        reacted += bool(stroke.feed(x, now))
    return reacted


def triggers() -> list[tuple[str, bool]]:
    results = []

    stroke = petting.Stroke()
    results.append(("a proper rub is noticed", rub(stroke, 6) >= 1))

    # It must react once per rub, not once per wobble -- otherwise a long
    # stroking session is a pet having a seizure.
    stroke = petting.Stroke()
    reacted = rub(stroke, 30, step=0.05)
    results.append((f"a long rub reacts sparingly ({reacted}x in 1.5s)", reacted == 1))

    # ...but keeps responding if you carry on past the cooldown.
    stroke = petting.Stroke()
    first = rub(stroke, 8, start=0.0)
    second = rub(stroke, 8, start=petting.COOLDOWN_SECONDS + 1.0)
    results.append(("stroking again later is noticed again", first >= 1 and second >= 1))
    return results


def directions() -> list[tuple[str, bool]]:
    """The gesture counts however it is oriented.

    Reported as not working at all, and this was why: only horizontal movement
    was measured, so waving up and down at the pet did nothing whatever --
    which nobody would guess was deliberate, and plenty of people wave that
    way.
    """
    import math

    def wave(axis: str, seconds: float = 1.2, hz: float = 1.5, amplitude: int = 130) -> bool:
        stroke = petting.Stroke()
        moment = 0.0
        while moment < seconds:
            offset = amplitude * math.sin(2 * math.pi * hz * moment)
            if axis == "x":
                x, y = 600 + offset, 500
            elif axis == "y":
                x, y = 600, 500 + offset
            else:
                x, y = 600 + offset * 0.7, 500 + offset * 0.7
            if stroke.feed(int(x), moment, int(y)):
                return True
            moment += 0.05
        return False

    results = [(f"waving along {axis} is noticed", wave(axis)) for axis in ("x", "y", "diagonal")]

    # y is optional, so a caller with only one axis to give still works.
    stroke = petting.Stroke()
    fired = any(stroke.feed(600 + FAR * (1 if i % 2 == 0 else -1), i * 0.1) for i in range(8))
    results.append(("x alone still works", fired))
    return results


def summons() -> list[tuple[str, bool]]:
    """A summons asks for less turning than a rub, and has to.

    A rub happens on a sprite a hundred pixels wide and gives half a turn per
    sweep, so it can ask for plenty. A summons is often a circle drawn at arm's
    length, and a big circle at an ordinary hand speed takes seconds per
    revolution -- asking for more than one meant a normal-sized circle never
    finished in time and looked like the gesture did nothing.
    """
    import math

    def circle(radius: int, speed: float, seconds: float = 3.0) -> bool:
        stroke = petting.Stroke(petting.CALL_TURN_RADIANS, petting.CALL_SPAN_PIXELS,
                                one_way=True, seconds=petting.CALL_SECONDS)
        moment = 0.0
        turns_per_second = speed / (2 * math.pi * radius)
        while moment < seconds:
            angle = 2 * math.pi * turns_per_second * moment
            if stroke.feed(int(700 + radius * math.cos(angle)), moment,
                           int(500 + radius * math.sin(angle))):
                return True
            moment += 0.05
        return False

    results = [("a summons asks less than a rub",
                petting.CALL_TURN_RADIANS < petting.TURN_RADIANS)]
    # Quick ones, at the pace the rule asks for.
    for radius, speed in ((45, 700), (60, 900), (100, 1500), (150, 2200)):
        results.append((f"a circle of radius {radius} drawn quickly is a summons",
                        circle(radius, speed)))

    # And the consequence, stated rather than left to be discovered: a big
    # circle cannot be carried round fast enough by hand, so it is no longer
    # a summons however well drawn. That is the rule working, not failing.
    for radius, speed in ((250, 1200), (400, 2000)):
        results.append((f"a radius {radius} circle at hand speed is too slow now",
                        not circle(radius, speed)))
    # A rub is still a rub: the stricter threshold is the default.
    results.append(("the default is still the stricter one",
                    petting.Stroke().turn_radians == petting.TURN_RADIANS))

    # Turning alone says nothing about how big a thing was drawn, and a
    # twirl of the wrist turns a full circle in no distance at all -- so the
    # pet came for gestures far smaller than anyone meant to make.
    for radius in (10, 20, 30):
        results.append((f"a circle only {2 * radius}px across is not a summons",
                        not circle(radius, 700)))
    results.append(("...but a coin-sized one is", circle(45, 700)))

    # Size was measured across the widest part alone, so a long thin loop
    # counted as a circle -- and reported as such: shapes nobody would call
    # round were summoning the pet.
    def ellipse(across: int, down: int, seconds: float = 2.0) -> bool:
        stroke = petting.Stroke(petting.CALL_TURN_RADIANS, petting.CALL_SPAN_PIXELS,
                                one_way=True, seconds=petting.CALL_SECONDS)
        moment = 0.0
        while moment < seconds:
            angle = 2 * math.pi * moment / 0.35  # a quick flick of a loop
            if stroke.feed(int(700 + across * math.cos(angle) / 2), moment,
                           int(500 + down * math.sin(angle) / 2)):
                return True
            moment += 0.05
        return False

    for across, down in ((400, 120), (500, 80), (600, 50), (120, 500), (300, 150)):
        results.append((f"a {across}x{down} sliver is not a summons",
                        not ellipse(across, down)))

    # Turned on its side. Reported as working -- a sliver drawn cornerwise
    # summoned the pet -- because roundness compared the bounding box, and
    # the box round a 400x120 ellipse at 45 degrees is 294x294, a perfect
    # square. The shape is now measured through its own axes instead.
    def turned(across: int, down: int, degrees: float, seconds: float = 2.0) -> bool:
        stroke = petting.Stroke(petting.CALL_TURN_RADIANS, petting.CALL_SPAN_PIXELS,
                                one_way=True, seconds=petting.CALL_SECONDS)
        angle_offset = math.radians(degrees)
        moment = 0.0
        while moment < seconds:
            angle = 2 * math.pi * moment / 0.35
            flat_x, flat_y = across / 2 * math.cos(angle), down / 2 * math.sin(angle)
            x = 900 + flat_x * math.cos(angle_offset) - flat_y * math.sin(angle_offset)
            y = 500 + flat_x * math.sin(angle_offset) + flat_y * math.cos(angle_offset)
            if stroke.feed(int(x), moment, int(y)):
                return True
            moment += 0.05
        return False

    for degrees in (30, 45, 60, 135):
        results.append((f"a sliver turned {degrees} degrees is not a summons either",
                        not turned(400, 120, degrees)))
    for degrees in (0, 45, 90):
        results.append((f"a real oval turned {degrees} degrees still is",
                        turned(240, 180, degrees)))

    # The measure itself, stated directly: it must not care which way up the
    # screen is, which is the whole of what went wrong.
    def shape_of(across: int, down: int, degrees: float) -> float:
        stroke = petting.Stroke()
        angle_offset = math.radians(degrees)
        for step in range(24):
            angle = 2 * math.pi * step / 24
            flat_x, flat_y = across / 2 * math.cos(angle), down / 2 * math.sin(angle)
            stroke.feed(int(900 + flat_x * math.cos(angle_offset)
                             - flat_y * math.sin(angle_offset)), step * 0.02,
                        int(500 + flat_x * math.sin(angle_offset)
                            + flat_y * math.cos(angle_offset)))
        return stroke.roundness()

    flat = shape_of(400, 120, 0)
    cornerwise = shape_of(400, 120, 45)
    results.append((f"roundness ignores rotation ({flat:.2f} flat, {cornerwise:.2f} at 45)",
                    abs(flat - cornerwise) < 0.05))
    results.append(("a circle scores near 1", shape_of(200, 200, 0) > 0.95))
    results.append(("a sliver scores near 0", shape_of(400, 20, 30) < 0.15))
    # What the bounding box would have said about that same sliver, which is
    # why it was believed.
    results.append(("...where the bounding box called it a circle",
                    abs(shape_of(400, 120, 45) - 1.0) > 0.4))
    # Nobody draws a true circle freehand, so an oval still has to count.
    for across, down in ((180, 180), (240, 180), (300, 200)):
        results.append((f"a {across}x{down} oval is still a summons",
                        ellipse(across, down)))
    results.append(("roundness is not asked of a rub", petting.Stroke().span_pixels == 0))

    # Pace. There was no limit on the gesture at all, only on the gap between
    # samples, so a circle drawn at a wandering pace over several seconds
    # counted exactly as a quick one did -- and a pointer crossing the screen
    # slowly does go round eventually. Drawing a circle on purpose is quick.
    def paced(seconds_per_turn: float, radius: int = 90, watch: float = 8.0) -> bool:
        stroke = petting.Stroke(petting.CALL_TURN_RADIANS, petting.CALL_SPAN_PIXELS,
                                one_way=True, seconds=petting.CALL_SECONDS)
        moment = 0.0
        while moment < watch:
            angle = 2 * math.pi * moment / seconds_per_turn
            if stroke.feed(int(700 + radius * math.cos(angle)), moment,
                           int(500 + radius * math.sin(angle))):
                return True
            moment += 0.05
        return False

    for pace in (0.25, 0.4):
        results.append((f"a circle drawn in {pace}s is a summons", paced(pace)))
    for pace in (0.8, 1.5, 3.0):
        results.append((f"one taking {pace}s is not", not paced(pace)))
    # Going round and round slowly must not add up to one either, which is
    # what a limit on the gap between samples alone would have allowed.
    results.append(("...however long it keeps going", not paced(1.5, watch=30.0)))
    results.append(("a rub is not put on the clock", petting.Stroke().seconds == 0.0))

    # Stroking asks for no minimum size: it happens on a sprite barely a
    # hundred pixels wide, and could not ask for one.
    results.append(("a rub has no size requirement", petting.Stroke().span_pixels == 0))

    # Only going round counts. Waving the pointer about while working was
    # summoning the pet, because adding up the sizes of the turns cannot
    # tell a circle from a wave -- the wave's turns cancel out only if the
    # sign is kept.
    def wave(axis: str, seconds: float = 3.0) -> bool:
        stroke = petting.Stroke(petting.CALL_TURN_RADIANS, petting.CALL_SPAN_PIXELS,
                                one_way=True, seconds=petting.CALL_SECONDS)
        moment = 0.0
        while moment < seconds:
            offset = 150 * math.sin(2 * math.pi * 1.5 * moment)
            x = 700 + (offset if axis in ('x', 'diagonal') else 0)
            y = 500 + (offset if axis in ('y', 'diagonal') else 0)
            if stroke.feed(int(x), moment, int(y)):
                return True
            moment += 0.05
        return False

    for axis in ('x', 'y', 'diagonal'):
        results.append((f"waving along {axis} is not a summons", not wave(axis)))
    results.append(("a reversal is not counted as going round",
                    petting.REVERSAL_RADIANS < math.pi))
    return results


def stars() -> list[tuple[str, bool]]:
    """A star teleports the pet, so it must be a star and not a scribble.

    Traced at a constant hand speed along the real path, sampled at the
    overlay's own 50ms, and repeated at several sampling offsets -- because
    the first attempt measured each corner from a single pair of samples, and
    a sample landing on a point splits its 144 degrees into two 72s, neither
    of which is a corner. Five points give that several chances to happen,
    which is why it was reported as simply not working.
    """
    import math

    def trace(points, seconds: float, jitter: float = 0.0, phase: float = 0.0,
              star=None) -> bool:
        """Walk a closed polyline at constant speed; True if it fired."""
        detector = star if star is not None else petting.Star()
        lengths = [math.hypot(points[i + 1][0] - points[i][0],
                              points[i + 1][1] - points[i][1])
                   for i in range(len(points) - 1)]
        speed = sum(lengths) / seconds
        moment = phase
        while moment < seconds:
            wanted, walked, spot = speed * moment, 0.0, None
            for index, length in enumerate(lengths):
                if walked + length >= wanted:
                    along = (wanted - walked) / length
                    spot = (points[index][0] + along * (points[index + 1][0] - points[index][0]),
                            points[index][1] + along * (points[index + 1][1] - points[index][1]))
                    break
                walked += length
            if spot is None:
                break
            x, y = spot
            if jitter:
                x += math.sin(moment * 37) * jitter
                y += math.cos(moment * 41) * jitter
            if detector.feed(int(x), moment, int(y)):
                return True
            moment += 0.05
        return False

    def pentagram(radius: int = 140, skew: float = 1.0):
        points = [(700 + radius * math.cos(math.radians(-90 + 144 * i)) * skew,
                   500 + radius * math.sin(math.radians(-90 + 144 * i)))
                  for i in range(5)]
        return points + [points[0]]

    def polygon(sides: int, radius: int = 140):
        points = [(700 + radius * math.cos(2 * math.pi * i / sides),
                   500 + radius * math.sin(2 * math.pi * i / sides))
                  for i in range(sides)]
        return points + [points[0]]

    def ring(radius: int = 140):
        return [(700 + radius * math.cos(2 * math.pi * i / 60),
                 500 + radius * math.sin(2 * math.pi * i / 60)) for i in range(61)]

    results = []
    for seconds in (0.8, 1.2, 1.8, 2.4):
        for phase in (0.0, 0.017, 0.033):
            results.append((f"a star drawn in {seconds}s is one (offset {phase:.3f})",
                            trace(pentagram(), seconds, phase=phase)))
    results.append(("a wobbly lopsided star still is",
                    trace(pentagram(skew=0.8), 1.5, jitter=6)))
    results.append(("a small one does too", trace(pentagram(radius=70), 1.2)))

    # Five points, but only four corners are ever seen: the closing edge ends
    # where the drawing started rather than carrying on through it. Asking for
    # five would mean asking for something that never arrives -- which is only
    # obvious once counted.
    counter = petting.Star(corners=99, seconds=10.0)
    trace(pentagram(), 1.5, star=counter)
    results.append((f"five points draw four corners ({counter.corners})",
                    counter.corners == 4))
    results.append(("...which is what is asked for", petting.STAR_CORNERS == 4))

    # The shapes it must not be. A circle is the one that matters, since a
    # circle already means something else.
    for seconds in (0.6, 1.0, 2.5):
        results.append((f"a circle drawn in {seconds}s is not a star",
                        not trace(ring(), seconds)))
    for sides, name in ((3, "triangle"), (4, "square"), (6, "hexagon"), (8, "octagon")):
        results.append((f"a {name} is not a star", not trace(polygon(sides), 1.5)))
    results.append(("a zigzag is not a star",
                    not trace([(500 + i * 90, 500 + (i % 2) * 160) for i in range(8)], 1.5)))
    results.append(("a straight line is not a star",
                    not trace([(400, 500), (1200, 500)], 1.0)))

    # Too small to be meant, and too slow to be one gesture.
    results.append(("a tiny star is not a summons to anywhere",
                    not trace(pentagram(radius=25), 1.0)))
    results.append(("one dawdled over is not either",
                    not trace(pentagram(), petting.STAR_SECONDS + 3.0)))

    # A star gets longer than a circle does, being more drawing.
    results.append(("a star is allowed longer than a circle",
                    petting.STAR_SECONDS > petting.CALL_SECONDS))
    # And it must not also read as a circle, or the pet would walk over as
    # well as appear.
    circle_too = petting.Stroke(petting.CALL_TURN_RADIANS, petting.CALL_SPAN_PIXELS,
                                one_way=True, seconds=petting.CALL_SECONDS)
    results.append(("...and does not read as a circle as well",
                    not trace(pentagram(), 1.2, star=circle_too)))
    return results


def rejects() -> list[tuple[str, bool]]:
    """The half that matters more: things that must never read as affection."""
    results = []

    # Crossing the sprite on the way somewhere else. No reversal, so no pet.
    stroke = petting.Stroke()
    reacted = 0
    for step in range(12):
        reacted += bool(stroke.feed(500 + step * FAR, step * 0.05))
    results.append(("a pointer passing straight across is ignored", reacted == 0))

    # A hand resting on the mouse: plenty of jitter, none of it deliberate.
    stroke = petting.Stroke()
    reacted = 0
    for step in range(60):
        reacted += bool(stroke.feed(500 + (step % 2) * 2, step * 0.05))
    results.append(("jitter on a resting hand is ignored", reacted == 0))

    # Two turns far apart are two hesitations, not one gesture.
    stroke = petting.Stroke()
    reacted = 0
    for index in range(6):
        reacted += bool(stroke.feed(500 + FAR * (1 if index % 2 == 0 else -1),
                                    index * (petting.WINDOW_SECONDS + 0.5)))
    results.append(("reversals far apart do not add up", reacted == 0))

    # Just under the amount of turning required. One rub back and forth is
    # a single half-turn; the threshold is above a full circle.
    stroke = petting.Stroke()
    reacted = rub(stroke, 3)
    results.append(("just under the threshold does not fire", reacted == 0))

    # A circle is what a wave and a rub have in common -- turning -- so the
    # threshold is stated in those terms and checked here.
    import math

    stroke = petting.Stroke()
    turned = 0
    for step in range(40):
        angle = 2 * math.pi * step / 20  # two full circles
        turned += bool(stroke.feed(int(600 + 60 * math.cos(angle)), step * 0.05,
                                   int(500 + 60 * math.sin(angle))))
    results.append(("a circle counts as a gesture", turned >= 1))

    # A drag is not a stroke, and the overlay resets on one.
    stroke = petting.Stroke()
    rub(stroke, 3)
    stroke.reset()
    results.append(("reset forgets a gesture in progress", stroke.turned == 0.0))
    return results


def main() -> int:
    failures = 0
    total = 0
    for label, results in (("triggers", triggers()), ("directions", directions()),
                            ("summons", summons()), ("stars", stars()),
                            ("rejects", rejects())):
        print(f"{label}:")
        for name, ok in results:
            total += 1
            failures += not ok
            print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
