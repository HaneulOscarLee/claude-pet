"""Recognising a pet being stroked.

Kept apart from the overlay, and stdlib-only, so the gesture can be tested
without a display -- which matters here more than most places, because the
whole difficulty is a judgement call about intent. Nothing distinguishes
"stroking the pet" from "moving the pointer across it" except that a stroke
turns around, and a rule about that is only as good as the cases it is tried
against.

Direction is what counts, not distance. Movements too small to be deliberate
are discarded, so a hand resting on a mouse never accumulates into affection,
and reversals expire, so two turns a minute apart are not one gesture.
"""

from __future__ import annotations

import math

#: How far the pointer must travel before a movement counts as a stroke at all,
#: rather than the hand shaking on a stationary mouse.
STROKE_PIXELS = 8

#: How far the pointer's direction must turn, in total, to count as a
#: gesture. Radians.
#:
#: Counting reversals -- turns of more than a right angle -- worked for
#: rubbing back and forth and could never work for a circle, which turns
#: gradually and reverses never. Accumulated turning covers both: half a
#: turn per reversal of a rub, a full turn per loop of a circle. Set a
#: little above one circle, so a small deliberate loop is enough and the
#: ordinary curve of a pointer on its way somewhere is not.
TURN_RADIANS = 2.2 * math.pi

#: What a summons asks for: about four fifths of a circle. Less than a rub,
#: because the gesture is bigger and therefore slower.
CALL_TURN_RADIANS = 1.6 * math.pi

#: Past this, a change of direction is a reversal rather than a curve.
#: Three quarters of a half-turn: enough room for a hand drawing a circle
#: in coarse steps, far from the doubling back of a wave.
REVERSAL_RADIANS = 0.75 * math.pi

#: How big the gesture has to be, measured across whatever it drew.
#:
#: Turning alone does not say how large a thing was drawn, and a tiny
#: twirl of the wrist accumulates a full turn in no distance at all -- so
#: the pet came for gestures far smaller than anyone meant to make. About
#: a coin across, which is small enough to be no effort and large enough
#: to be deliberate.
CALL_SPAN_PIXELS = 90

#: How round it has to be: the shorter side of what was drawn, as a
#: fraction of the longer.
#:
#: Size alone was measured across the widest part, so a long thin loop --
#: or a squiggle that happened to double back -- counted as a circle.
#: Nobody draws a true circle freehand, so there is room here, but not much:
#: at three fifths a 300x180 oval still counts and a 300x150 one does not.
CALL_ROUNDNESS = 0.6

#: How long the whole gesture may take, from the first turn to the last.
#:
#: There was no limit at all, only a limit on the gap between samples, so a
#: circle drawn at a leisurely pace over several seconds counted exactly as
#: a quick one did -- and the pointer wanders round the screen slowly all
#: day. Drawing a circle *deliberately* is a quick thing; this is what
#: separates it from having merely gone that way eventually.
CALL_SECONDS = 1.2

#: Reversals only belong to the same gesture within this long of each other.
WINDOW_SECONDS = 1.6

#: A pet reacting to every stroke of a long rub is a pet having a seizure.
COOLDOWN_SECONDS = 2.5


class Stroke:
    """Tracks a hovering pointer and says when it has been stroking.

    `feed` is given the pointer's x and the time, and returns True on the
    moment the gesture completes -- once per rub, not once per wobble.
    """

    def __init__(
        self,
        turn_radians: float = TURN_RADIANS,
        span_pixels: int = 0,
        one_way: bool = False,
        seconds: float = 0.0,
    ) -> None:
        #: Stroking and summoning want different amounts of it. A rub gives
        #: half a turn per sweep and happens on a sprite barely a hundred
        #: pixels wide, so it can ask for a lot; a summons is often a circle
        #: drawn at arm's length, and a big circle at an ordinary hand speed
        #: takes seconds per revolution -- ask for more than one and a
        #: normal-sized circle never finishes in time.
        self.turn_radians = turn_radians
        #: How far the gesture must reach across, if at all. Stroking a
        #: sprite is confined to the sprite and cannot ask for much; a
        #: summons drawn anywhere on screen can.
        self.span_pixels = span_pixels
        #: Whether the turning has to keep going the same way round.
        #:
        #: A circle does; a wave does not, its turns cancelling out. Adding
        #: up the sizes of the turns cannot tell them apart, so waving the
        #: pointer about while working summoned the pet. Keeping the sign
        #: separates them exactly: two loops of a circle come to +3.9pi,
        #: the same length of wave to 0.
        self.one_way = one_way
        #: How long the whole gesture may take; 0 for no limit.
        #:
        #: A rub needs none -- it happens on the sprite, where nothing else
        #: is going on. A summons is drawn out in the open, where the
        #: pointer travels all day, and without this the only thing
        #: separating "drew a circle" from "went round eventually" was that
        #: no single pause exceeded the sample window.
        self.seconds = seconds
        self.began = 0.0
        self.low_x = self.high_x = 0
        self.low_y = self.high_y = 0
        self.x: int | None = None
        self.y = 0
        self.at = 0.0
        self.direction_x = 0.0
        self.direction_y = 0.0
        self.turned = 0.0
        self.turned_signed = 0.0
        self.ready_at = 0.0

    def reset(self) -> None:
        """Forget the gesture in progress, when the pointer leaves or drags."""
        self.x = None
        self.began = 0.0
        self.direction_x = 0.0
        self.direction_y = 0.0
        self.turned = self.turned_signed = 0.0
        self.low_x = self.high_x = 0
        self.low_y = self.high_y = 0

    def feed(self, x: int, now: float, y: int = 0) -> bool:
        """Feed a pointer position. `y` is optional; without it, x alone decides.

        Direction is a vector, not a sign, so a gesture counts however it is
        oriented. Watching only x meant waving up and down at the pet did
        nothing at all -- which is not a thing anyone would guess was
        deliberate, and several people wave that way.
        """
        if self.x is None:
            self.x, self.y, self.at = x, y, now
            self.began = now
            self.low_x = self.high_x = x
            self.low_y = self.high_y = y
            return False

        travelled_x = x - self.x
        travelled_y = y - self.y
        if math.hypot(travelled_x, travelled_y) < STROKE_PIXELS:
            # Too small to mean anything. Deliberately does not update the
            # anchor: a slow drag across the sprite would otherwise never
            # accumulate enough travel to register at all.
            return False

        too_slow = bool(self.seconds) and now - self.began > self.seconds
        if now - self.at > WINDOW_SECONDS or too_slow:
            # Whatever came before was a different gesture -- either too long
            # ago to belong to this one, or too long in the drawing to have
            # been one. Start again from here rather than discarding the
            # sample: the circle someone is drawing right now may well be the
            # deliberate one.
            self.turned = self.turned_signed = 0.0
            self.low_x = self.high_x = x
            self.low_y = self.high_y = y
            self.began = now
        self.low_x, self.high_x = min(self.low_x, x), max(self.high_x, x)
        self.low_y, self.high_y = min(self.low_y, y), max(self.high_y, y)
        if self.direction_x or self.direction_y:
            # The angle between one movement and the next, added up. A rub
            # turns half a circle every time it goes back; a circle turns a
            # whole one each loop; a pointer crossing the sprite on its way
            # somewhere turns almost nothing.
            angle = math.atan2(
                self.direction_x * travelled_y - self.direction_y * travelled_x,
                self.direction_x * travelled_x + self.direction_y * travelled_y,
            )
            self.turned += abs(angle)
            # A turn of nearly half a circle is a reversal, not a rotation,
            # and must not count towards going round. It also has no
            # reliable sign: reverse exactly and the cross product is zero,
            # so atan2 answers +pi every time and a plain back-and-forth
            # accumulates in one direction exactly as a circle would.
            if abs(angle) < REVERSAL_RADIANS:
                self.turned_signed += angle
        self.direction_x, self.direction_y = float(travelled_x), float(travelled_y)
        self.x, self.y, self.at = x, y, now

        wide = self.high_x - self.low_x
        tall = self.high_y - self.low_y
        span = max(wide, tall)
        turning = abs(self.turned_signed) if self.one_way else self.turned
        round_enough = not self.span_pixels or min(wide, tall) >= span * CALL_ROUNDNESS
        if (
            turning < self.turn_radians
            or span < self.span_pixels
            or not round_enough
            or now < self.ready_at
        ):
            return False
        self.turned = self.turned_signed = 0.0
        self.low_x = self.high_x = x
        self.low_y = self.high_y = y
        self.began = now
        self.ready_at = now + COOLDOWN_SECONDS
        return True
