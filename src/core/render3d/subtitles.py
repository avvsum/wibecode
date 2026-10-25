"""Subtitle overlay for "say" lines: white text on top, *word* highlighted."""

from __future__ import annotations

from PIL import Image, ImageDraw

from src.core.renderer import HEIGHT, WIDTH, _font

TEXT = (255, 255, 255)
HIGHLIGHT = (255, 150, 70)
OUTLINE = (20, 12, 10)
TOP = int(HEIGHT * 0.1)


def words(text: str) -> list[tuple[str, bool, bool]]:
    """Split into (word, highlighted, glued). glued: no space before the word,
    as in "*ролики*?" where "?" sticks to the highlight. Unpaired "*" stay as is."""
    parts = [text] if text.count("*") % 2 else text.split("*")
    out, before = [], ""  # before: the text right before the current part
    for i, part in enumerate(parts):
        for j, word in enumerate(part.split()):
            touching = not part[:1].isspace() and not before[-1:].isspace()
            out.append((word, i % 2 == 1, j == 0 and bool(out) and touching))
        before = part or before
    return out


def subtitle(text: str) -> Image.Image:
    """Transparent WIDTHxHEIGHT image with the line wrapped near the top."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    max_width = int(WIDTH * 0.88)
    for size in (64, 56, 48, 40):
        font = _font(size)
        space = draw.textlength(" ", font=font)
        lines, line, width = [], [], 0.0
        for word, hl, glued in words(text):
            w = draw.textlength(word, font=font)
            gap = 0.0 if glued or not line else space
            if line and not glued and width + gap + w > max_width:
                lines.append(line)
                line, width, gap = [], 0.0, 0.0
            width += gap + w
            line.append((word, hl, w, gap))
        if line:
            lines.append(line)
        if len(lines) <= 4:
            break
    y = TOP
    for line in lines:
        x = (WIDTH - sum(w + gap for _, _, w, gap in line)) / 2
        for word, hl, w, gap in line:
            x += gap
            draw.text(
                (x, y), word, font=font, fill=HIGHLIGHT if hl else TEXT,
                stroke_width=max(3, size // 12), stroke_fill=OUTLINE,
            )  # fmt: skip
            x += w
        y += int(size * 1.3)
    return img
