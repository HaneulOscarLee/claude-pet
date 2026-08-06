"""Generate the bundled default pet pack.

Committed alongside its output so the sprite in `assets/pets/pocket` is
reproducible and demonstrably original -- the repo can ship a working pet
without redistributing anyone else's art.

Drawn at 24x26 logical pixels and scaled up with nearest-neighbour, which is
what gives it the chunky pixel look at the 192x208 cell size the Codex pet
contract requires.

    python3 tools/make_default_pack.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

CELL = (192, 208)
LOGICAL = (24, 26)
SCALE = CELL[0] // LOGICAL[0]
COLUMNS = 8

BODY = (122, 162, 247, 255)
BODY_DARK = (86, 122, 200, 255)
BELLY = (196, 216, 255, 255)
EYE = (24, 28, 44, 255)
SHINE = (255, 255, 255, 255)
FOOT = (238, 190, 108, 255)
ACCENT = (247, 168, 184, 255)
SPARK = (255, 214, 102, 255)
TEAR = (128, 208, 240, 255)

#: row -> (name, frame count), per the Codex pet contract
ROWS = [
    ("idle", 6),
    ("running-right", 8),
    ("running-left", 8),
    ("waving", 4),
    ("jumping", 5),
    ("failed", 8),
    ("waiting", 6),
    ("running", 6),
    ("review", 6),
]


def blank() -> Image.Image:
    return Image.new("RGBA", LOGICAL, (0, 0, 0, 0))


def draw_body(
    canvas: ImageDraw.ImageDraw,
    *,
    lift: int = 0,
    squash: int = 0,
    lean: int = 0,
) -> tuple[int, int]:
    """Draw the blob. Returns the (x, y) of its head centre."""
    left = 5 + lean
    right = 18 + lean
    top = 7 - lift + squash
    bottom = 21 - lift

    canvas.rounded_rectangle([left, top, right, bottom], radius=6, fill=BODY)
    # Belly patch, a shade lighter, sitting low and centred.
    canvas.rounded_rectangle(
        [left + 4, top + 7, right - 4, bottom - 2], radius=4, fill=BELLY
    )
    # A single ear-tuft, so the silhouette is not a plain oval.
    canvas.polygon(
        [(left + 3, top + 1), (left + 6, top - 3), (left + 8, top + 2)], fill=BODY_DARK
    )
    return ((left + right) // 2, top + 5)


def draw_face(
    canvas: ImageDraw.ImageDraw,
    head: tuple[int, int],
    *,
    look: int = 0,
    closed: bool = False,
    sad: bool = False,
) -> None:
    center_x, center_y = head
    for offset in (-3, 3):
        x = center_x + offset + look
        if closed:
            canvas.line([(x - 1, center_y), (x + 1, center_y)], fill=EYE)
            continue
        y = center_y + (1 if sad else 0)
        canvas.rectangle([x - 1, y - 1, x, y + 1], fill=EYE)
        canvas.point((x - 1, y - 1), fill=SHINE)
    if sad:
        canvas.line(
            [(center_x - 1, center_y + 4), (center_x + 1, center_y + 4)], fill=BODY_DARK
        )
    else:
        canvas.point((center_x, center_y + 4), fill=ACCENT)


def draw_feet(canvas: ImageDraw.ImageDraw, *, stride: int = 0, lift: int = 0) -> None:
    base = 22 - lift
    canvas.rectangle([7 - stride, base, 10 - stride, base + 1], fill=FOOT)
    canvas.rectangle([13 + stride, base, 16 + stride, base + 1], fill=FOOT)


def draw_arm(canvas: ImageDraw.ImageDraw, *, angle: float, lift: int = 0) -> None:
    """A waving arm, swung by `angle` radians from straight down."""
    shoulder = (18, 14 - lift)
    length = 5
    tip = (
        int(round(shoulder[0] + math.sin(angle) * length)),
        int(round(shoulder[1] - math.cos(angle) * length)),
    )
    canvas.line([shoulder, tip], fill=BODY_DARK, width=1)
    canvas.point(tip, fill=BODY)


def frame_idle(index: int, total: int) -> Image.Image:
    image = blank()
    canvas = ImageDraw.Draw(image)
    lift = (0, 1, 1, 0, 0, 0)[index % 6]
    head = draw_body(canvas, lift=lift)
    # One slow blink per cycle, on the second-to-last frame.
    draw_face(canvas, head, closed=index == total - 2)
    draw_feet(canvas, lift=lift)
    return image


def frame_running(index: int, total: int, *, mirrored: bool) -> Image.Image:
    image = blank()
    canvas = ImageDraw.Draw(image)
    phase = index / max(1, total) * math.tau
    lift = 1 if math.sin(phase) > 0 else 0
    stride = int(round(math.sin(phase) * 2))
    head = draw_body(canvas, lift=lift, lean=1)
    draw_face(canvas, head, look=1)
    draw_feet(canvas, stride=stride, lift=lift)
    if mirrored:
        image = image.transpose(Image.FLIP_LEFT_RIGHT)
    return image


def frame_waving(index: int, total: int) -> Image.Image:
    image = blank()
    canvas = ImageDraw.Draw(image)
    head = draw_body(canvas)
    draw_face(canvas, head)
    draw_feet(canvas)
    swing = math.radians(150 + 35 * math.sin(index / max(1, total - 1) * math.pi))
    draw_arm(canvas, angle=swing)
    return image


def frame_jumping(index: int, total: int) -> Image.Image:
    image = blank()
    canvas = ImageDraw.Draw(image)
    progress = index / max(1, total - 1)
    lift = int(round(math.sin(progress * math.pi) * 4))
    squash = 1 if index in (0, total - 1) else 0
    head = draw_body(canvas, lift=lift, squash=squash)
    draw_face(canvas, head)
    draw_feet(canvas, stride=-1 if lift else 0, lift=lift)
    if lift:
        canvas.point((4, 20 - lift), fill=SPARK)
        canvas.point((19, 20 - lift), fill=SPARK)
    return image


def frame_failed(index: int, total: int) -> Image.Image:
    image = blank()
    canvas = ImageDraw.Draw(image)
    head = draw_body(canvas, squash=1)
    draw_face(canvas, head, sad=True)
    draw_feet(canvas)
    # A tear that forms, falls, and is gone again.
    stage = index / max(1, total - 1)
    if 0.2 < stage < 0.9:
        canvas.point((head[0] + 4, head[1] + 2 + int(stage * 6)), fill=TEAR)
    return image


def frame_waiting(index: int, total: int) -> Image.Image:
    image = blank()
    canvas = ImageDraw.Draw(image)
    lift = (0, 0, 1, 1, 0, 0)[index % 6]
    head = draw_body(canvas, lift=lift)
    draw_face(canvas, head, look=-1 if index % 4 < 2 else 1)
    draw_feet(canvas, lift=lift)
    # Question mark, blinking on and off above the head.
    if index % 4 < 2:
        canvas.line([(19, 4), (21, 4)], fill=SPARK)
        canvas.line([(21, 5), (20, 6)], fill=SPARK)
        canvas.point((20, 8), fill=SPARK)
    return image


def frame_working(index: int, total: int) -> Image.Image:
    image = blank()
    canvas = ImageDraw.Draw(image)
    lift = index % 2
    head = draw_body(canvas, lift=lift)
    draw_face(canvas, head, closed=index % 3 == 1)
    draw_feet(canvas, lift=lift)
    # Sparks cycling round, to read as busier than idle.
    for step in range(3):
        if (index + step) % 3 == 0:
            canvas.point((3 + step, 9 + step), fill=SPARK)
    return image


def frame_review(index: int, total: int) -> Image.Image:
    image = blank()
    canvas = ImageDraw.Draw(image)
    lift = (1, 1, 0, 0, 1, 1)[index % 6]
    head = draw_body(canvas, lift=lift)
    draw_face(canvas, head)
    draw_feet(canvas, lift=lift)
    draw_arm(canvas, angle=math.radians(165), lift=lift)
    # A tick, held up next to the raised arm.
    canvas.line([(2, 12), (4, 14)], fill=SPARK)
    canvas.line([(4, 14), (7, 9)], fill=SPARK)
    return image


BUILDERS = {
    "idle": frame_idle,
    "running-right": lambda i, n: frame_running(i, n, mirrored=False),
    "running-left": lambda i, n: frame_running(i, n, mirrored=True),
    "waving": frame_waving,
    "jumping": frame_jumping,
    "failed": frame_failed,
    "waiting": frame_waiting,
    "running": frame_working,
    "review": frame_review,
}


def build_atlas() -> Image.Image:
    atlas = Image.new("RGBA", (CELL[0] * COLUMNS, CELL[1] * len(ROWS)), (0, 0, 0, 0))
    for row, (name, count) in enumerate(ROWS):
        builder = BUILDERS[name]
        for column in range(count):
            cell = builder(column, count).resize(CELL, Image.NEAREST)
            atlas.alpha_composite(cell, (column * CELL[0], row * CELL[1]))
    return atlas


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "assets" / "pets" / "pocket"
    target.mkdir(parents=True, exist_ok=True)

    build_atlas().save(target / "spritesheet.webp", lossless=True)
    manifest = {
        "id": "pocket",
        "displayName": "Pocket",
        "description": "The bundled default pet. Drawn by tools/make_default_pack.py.",
        "spritesheetPath": "spritesheet.webp",
        "kind": "creature",
    }
    (target / "pet.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
