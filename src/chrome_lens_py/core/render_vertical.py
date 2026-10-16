"""Vertical (top-to-bottom) text for the overlay renderer.

This is CSS ``writing-mode: vertical-rl`` with the default ``text-orientation:
mixed``: ideographs, kana and hangul stand upright and stack, Latin runs lie on
their side rotated 90 degrees clockwise, and a handful of punctuation marks get
special treatment (see ``glyph_for``).
"""

import math
from functools import lru_cache
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw

from ..constants import RENDER_MAX_FONT_SIZE, RENDER_MIN_FONT_SIZE
from ..utils.font_fallback import face_has_glyph
from .render_common import composite
from .render_fonts import Face, FontPlan, SizedPlan

# Ranges CSS "text-orientation: mixed" keeps upright in vertical writing:
# kana, CJK ideographs, hangul, CJK punctuation and full-width forms. General
# punctuation that has a vertical form (dashes and the ellipsis leaders) is
# included so that it gets a cell of its own, like the CJK marks around it,
# instead of being measured as a sideways run of its natural width.
_UPRIGHT_RANGES = (
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x2010, 0x2015),  # Hyphen, dashes, horizontal bar
    (0x2025, 0x2026),  # Two-dot leader, horizontal ellipsis
    (0x2E80, 0x303F),  # CJK radicals, Kangxi, CJK symbols and punctuation
    (0x3041, 0x33FF),  # Hiragana, Katakana, Bopomofo, Kanbun, enclosed CJK
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xAC00, 0xD7AF),  # Hangul syllables
    (0xF900, 0xFAFF),  # CJK compatibility ideographs
    (0xFE10, 0xFE4F),  # Vertical and CJK compatibility forms
    (0xFF00, 0xFF60),  # Full-width forms
    (0xFFE0, 0xFFE6),  # Full-width signs
)

# Unicode's vertical presentation forms (U+FE10..FE19, U+FE30..FE48) are the
# glyphs a font would substitute through its `vert` feature, pre-rotated and
# pre-positioned for a vertical column. Pillow cannot apply OpenType features
# without Raqm, so the forms are used directly where the font has them.
_VERTICAL_FORMS: Dict[str, str] = {
    "，": "︐",
    "、": "︑",
    "。": "︒",
    "…": "︙",
    "‥": "︰",
    "—": "︱",
    "―": "︱",
    "–": "︲",
    "（": "︵",
    "）": "︶",
    "｛": "︷",
    "｝": "︸",
    "〔": "︹",
    "〕": "︺",
    "【": "︻",
    "】": "︼",
    "《": "︽",
    "》": "︾",
    "〈": "︿",
    "〉": "﹀",
    "「": "﹁",
    "」": "﹂",
    "『": "﹃",
    "』": "﹄",
    "［": "﹇",
    "］": "﹈",
}

# Marks with no presentation form, or in fonts that lack it, are turned a
# quarter turn clockwise - which is what the `vert` glyph is for all of these.
_VERTICAL_ROTATED_PUNCT = frozenset(
    "ー〜～‐‑‒–—―－…‥（）｛｝〔〕［］【】「」『』〈〉《》"
)

# Kuten and touten hang in the upper right of the em square.
_VERTICAL_CORNER_PUNCT = frozenset("、。，．")


def is_upright(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _UPRIGHT_RANGES)


@lru_cache(maxsize=256)
def vertical_runs(text: str) -> Tuple[Tuple[bool, str], ...]:
    """Split text into upright (CJK) and sideways (Latin) runs.

    Whitespace joins whichever run precedes it so a space between two kanji does
    not start a sideways run of its own.
    """
    runs = []
    for char in text:
        upright = is_upright(char)
        if char.isspace() and runs:
            upright = runs[-1][0]
        if runs and runs[-1][0] == upright:
            runs[-1] = (upright, runs[-1][1] + char)
        else:
            runs.append((upright, char))
    return tuple(runs)


def glyph_for(char: str, plan: FontPlan) -> Tuple[str, Face, bool]:
    """How one upright character is set: (glyph, face, rotate a quarter turn).

    A vertical presentation form is preferred when a face of the plan really has
    it. Otherwise dashes, brackets, the ellipsis and the long vowel mark are
    rotated, and everything else is drawn as it is.
    """
    face = plan.face_for(char)
    form = _VERTICAL_FORMS.get(char)
    if form:
        for candidate in (face,) + tuple(f for f in plan.faces if f != face):
            if candidate is not None and face_has_glyph(candidate, form):
                return form, candidate, False
    return char, face, char in _VERTICAL_ROTATED_PUNCT


def measure_vertical(text: str, font: SizedPlan) -> Tuple[float, float]:
    """Column width and total height of `text` set vertically."""
    ascent, descent = font.getmetrics()
    em = ascent + descent
    width = 0.0
    height = 0.0
    for upright, run in vertical_runs(text):
        if upright:
            # Each glyph occupies one em of column height.
            height += em * len(run)
            width = max(width, max(font.getlength(ch) for ch in set(run)))
        else:
            # A sideways run is as tall as it is long, and one em thick.
            height += font.getlength(run)
            width = max(width, float(em))
    return width, height


def fit_font_size_vertical(
    text: str, plan: FontPlan, box_width: float, box_height: float
) -> Tuple[SizedPlan, int]:
    """fit_font_size for a vertical column: width is the constraint, not length."""
    low, high = RENDER_MIN_FONT_SIZE, RENDER_MAX_FONT_SIZE
    while low <= high:
        mid = (low + high) // 2
        width, height = measure_vertical(text, plan.at(mid))
        if width >= box_width or height >= box_height:
            high = mid - 1
        else:
            low = mid + 1

    size = max(RENDER_MIN_FONT_SIZE, min(low - 1, RENDER_MAX_FONT_SIZE))
    return plan.at(size), size


def render_vertical_tile(
    text: str,
    font: SizedPlan,
    box_w: float,
    box_h: float,
    fill: Tuple[int, int, int, int],
    outline: int,
    outline_color: Optional[Tuple[int, int, int, int]],
    align: str,
    grow: bool = False,
) -> Image.Image:
    """Set text top-to-bottom in a narrow column, CJK glyphs upright.

    The tile is the size of the box and anything outside it is clipped, as in
    Chromium. With `grow` - used when the readable-size floor has made the text
    larger than its box - the tile is enlarged to the *measured* extent of the
    text instead, keeping the box centre and the alignment relative to the box,
    so nothing is cut off. The tile is only ever as large as the text it holds.
    """
    ascent, descent = font.getmetrics()
    em = ascent + descent
    col_w, total_h = measure_vertical(text, font)

    tile_w, tile_h = max(1, round(box_w)), max(1, round(box_h))
    ox = oy = 0.0
    if grow:
        edge = 2 * outline + 2
        need_w, need_h = math.ceil(col_w) + edge, math.ceil(total_h) + edge
        if need_w > tile_w:
            tile_w = need_w
            ox = (tile_w - box_w) / 2
        if need_h > tile_h:
            tile_h = need_h
            oy = (tile_h - box_h) / 2

    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)

    # Vertical alignment is the "start/center/end" of the column.
    y = oy + {
        "left": 0.0,
        "center": (box_h - total_h) / 2,
        "right": box_h - total_h,
    }.get(align, (box_h - total_h) / 2)

    def stamp(
        target: ImageDraw.ImageDraw, px: float, py: float, glyph: str, face: Face = None
    ):
        # Pillow strokes text natively. Chromium uses four offset copies only
        # because CSS has no portable text stroke, and that reads as an outline
        # only while the offset is a pixel or two - past that the copies
        # separate into ghosts with gaps between them.
        font.draw(
            target,
            (px, py),
            glyph,
            fill,
            stroke_width=outline if outline_color else 0,
            stroke_fill=outline_color,
            face=face,
        )

    def sideways(glyph: str, length: float, face: Face = None):
        # Draw on a strip lying down, then stand it up a quarter turn clockwise.
        pad = 2 * outline + 2
        sub = Image.new("RGBA", (max(1, round(length) + pad), em + pad), (0, 0, 0, 0))
        stamp(ImageDraw.Draw(sub), pad / 2, pad / 2, glyph, face)
        sub = sub.rotate(-90, expand=True)
        composite(tile, sub, round((box_w - sub.width) / 2 + ox), round(y - pad / 2))

    for upright, run in vertical_runs(text):
        if upright:
            for char in run:
                glyph, face, rotate = glyph_for(char, font.plan)
                advance = font.getlength(glyph)
                if rotate:
                    sideways(glyph, advance, face)
                elif glyph != char:
                    # A presentation form comes pre-positioned in its em cell.
                    stamp(draw, (box_w - advance) / 2 + ox, y, glyph, face)
                elif char in _VERTICAL_CORNER_PUNCT:
                    stamp(
                        draw,
                        (box_w - advance) / 2 + advance * 0.45 + ox,
                        y - em * 0.4,
                        char,
                    )
                else:
                    stamp(draw, (box_w - advance) / 2 + ox, y, char)
                y += em
        else:
            run_len = font.getlength(run)
            if run_len <= 0:
                continue
            sideways(run, run_len)
            y += run_len
    return tile
