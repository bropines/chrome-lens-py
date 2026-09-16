"""Render Lens translations the way Chromium's overlay does.

The server returns everything needed to repaint translated text in place: a
per-line inpainted background patch, foreground/background colours, per-line
character ranges into the translated string, writing direction and alignment.
This module reproduces Chromium's rendering of that data.

Reference implementation:
  chrome/browser/resources/lens/overlay/text_layer.ts
    - calculateFontSizePixels()   -> binary search, font bounding box metrics
    - getTranslatedLineStyle()    -> colours, alignment, rotation, padding
    - getBackgroundImageDataStyle() -> patch size from paddings and aspect ratio
    - getOutlineStyleForLine()    -> text-shadow outline at fontSize * 0.02
  chrome/browser/ui/lens/lens_overlay_proto_converter.cc
    - CreateTranslatedLineMojomFromProto() -> UTF-16 slicing of the translation
"""

import io
import logging
import math
from typing import TYPE_CHECKING, Any, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, features

from ..constants import (
    RENDER_MAX_FONT_SIZE,
    RENDER_MIN_FONT_SIZE,
    RENDER_OUTLINE_RATIO,
    RTL_LANGUAGES,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..utils.lens_betterproto import LensOverlayObjectsResponse

logger = logging.getLogger(__name__)

_TRANSLATION_STATUS_SUCCESS = 1
_WRITING_DIRECTION_RTL = 1
_WRITING_DIRECTION_TOP_TO_BOTTOM = 2

# Alignment enum -> horizontal placement inside the line box.
_ALIGNMENT = {0: "left", 1: "right", 2: "center"}

_shaping_warned = False


def _argb_to_rgba(value: int) -> Tuple[int, int, int, int]:
    """Convert the server's aRGB uint32 into Pillow's RGBA tuple."""
    return (
        (value >> 16) & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF,
        (value >> 24) & 0xFF,
    )


def _u16_slice(text: str, start: int, end: int) -> str:
    """Slice by UTF-16 code units.

    The server's word offsets are what icu::UnicodeString uses, which indexes
    UTF-16 code units. Python strings index code points, so anything outside the
    BMP (emoji, rare CJK) would drift if we sliced directly.
    """
    if start >= end:
        return ""
    encoded = text.encode("utf-16-le")
    return encoded[2 * start : 2 * end].decode("utf-16-le", errors="replace")


def build_line_text(translation: str, line: Any, next_line: Optional[Any]) -> str:
    """Reassemble one rendered line from the flat translation string.

    Mirrors CreateTranslatedLineMojomFromProto: each word is a range into the
    paragraph-wide translation, and the separator after a word is the gap up to
    the next word - crossing into the following line for the last word.
    """
    words = list(line.word)
    if not words:
        return ""

    parts: List[str] = []
    for index, word in enumerate(words):
        parts.append(_u16_slice(translation, word.start, word.end))
        if index < len(words) - 1:
            parts.append(_u16_slice(translation, word.end, words[index + 1].start))
        elif next_line is not None and len(next_line.word) > 0:
            parts.append(_u16_slice(translation, word.end, next_line.word[0].start))
    return "".join(parts)


def _has_rtl(text: str) -> bool:
    for char in text:
        code = ord(char)
        if (
            0x0590 <= code <= 0x08FF
            or 0xFB1D <= code <= 0xFDFF
            or 0xFE70 <= code <= 0xFEFF
        ):
            return True
    return False


def shape_for_display(text: str, is_rtl: bool) -> str:
    """Return text in visual order, shaped for fonts Pillow can draw.

    Pillow only does bidi reordering and Arabic glyph joining when it was built
    against libraqm, and the published wheels are not. Without that, RTL text
    renders as disconnected letters in logical order. python-bidi and
    arabic-reshaper cover the gap; when neither Raqm nor those are available we
    warn once and draw the text unshaped rather than failing.
    """
    global _shaping_warned

    if not (is_rtl or _has_rtl(text)):
        return text

    if features.check("raqm"):
        # Pillow handles bidi + shaping itself; passing it through unchanged.
        return text

    try:
        import arabic_reshaper  # type: ignore
        from bidi.algorithm import get_display  # type: ignore

        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        if not _shaping_warned:
            _shaping_warned = True
            logger.warning(
                "Right-to-left text detected but this Pillow has no Raqm support "
                "and python-bidi/arabic-reshaper are not installed. RTL text will "
                'render unshaped. Install with: pip install "chrome-lens-py[rtl]"'
            )
        return text


def _load_font(font_path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    size = max(RENDER_MIN_FONT_SIZE, min(int(size), RENDER_MAX_FONT_SIZE))
    return (
        ImageFont.truetype(font_path, size)
        if font_path
        else ImageFont.load_default(size)
    )


def fit_font_size(
    text: str, font_path: Optional[str], box_width: float, box_height: float
) -> Tuple[ImageFont.FreeTypeFont, int]:
    """Largest font size whose text fits the line box, by binary search.

    This is calculateFontSizePixels(). Two details matter and are easy to get
    wrong: the height test uses the font's bounding box (ascent + descent), not
    the ink extents of these particular glyphs, and the comparison is strictly
    "greater or equal fails", so the winning size always leaves a little slack.
    Chromium never wraps a translated line - it scales the text down instead.
    """
    cache: dict = {}

    def load(size: int) -> ImageFont.FreeTypeFont:
        if size not in cache:
            cache[size] = (
                ImageFont.truetype(font_path, size)
                if font_path
                else ImageFont.load_default(size)
            )
        return cache[size]

    low, high = RENDER_MIN_FONT_SIZE, RENDER_MAX_FONT_SIZE
    while low <= high:
        mid = (low + high) // 2
        font = load(mid)
        ascent, descent = font.getmetrics()
        if font.getlength(text) >= box_width or (ascent + descent) >= box_height:
            high = mid - 1
        else:
            low = mid + 1

    size = max(RENDER_MIN_FONT_SIZE, min(low - 1, RENDER_MAX_FONT_SIZE))
    return load(size), size


# Ranges CSS "text-orientation: mixed" keeps upright in vertical writing:
# kana, CJK ideographs, hangul, CJK punctuation and full-width forms.
_UPRIGHT_RANGES = (
    (0x1100, 0x11FF),  # Hangul Jamo
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


def _box_corners(box, width: int, height: int) -> List[Tuple[float, float]]:
    """The four corners of a rotated line box, in image pixels."""
    cx, cy = box.center_x * width, box.center_y * height
    half_w, half_h = box.width * width / 2, box.height * height / 2
    # Pillow draws counter-clockwise; rotation_z is clockwise.
    angle = -box.rotation_z
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return [
        (cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a)
        for dx, dy in (
            (-half_w, -half_h),
            (half_w, -half_h),
            (half_w, half_h),
            (-half_w, half_h),
        )
    ]


def _convex_hull(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Andrew's monotone chain."""
    if len(points) < 3:
        return list(points)

    ordered = sorted(set(points))

    def half(seq):
        chain: List[Tuple[float, float]] = []
        for point in seq:
            while len(chain) >= 2:
                (ox, oy), (ax, ay) = chain[-2], chain[-1]
                if (ax - ox) * (point[1] - oy) - (ay - oy) * (point[0] - ox) > 0:
                    break
                chain.pop()
            chain.append(point)
        return chain[:-1]

    return half(ordered) + half(reversed(ordered))


def _erase_text_area(canvas: Image.Image, paragraph, data, padding: float) -> None:
    """Cover the whole area the source text occupied, in one shape.

    The server's inpainting erases glyphs but keeps their anti-aliased edges,
    and on a page of vertical text that residue reads as noise. The paragraph's
    bounding box is the wrong shape to cover it with: for columns at an angle,
    or ragged lines, a rectangle takes in far more than the text and an ellipse
    inscribed in it takes in too little at the corners. The hull of every line
    box's corners is exactly the text's extent.
    """
    width, height = canvas.size
    points: List[Tuple[float, float]] = []
    thinnest = float("inf")

    for line in paragraph.lines:
        if not line.HasField("geometry"):
            continue
        box = line.geometry.bounding_box
        points.extend(_box_corners(box, width, height))
        thinnest = min(thinnest, box.width * width, box.height * height)

    hull = _convex_hull(points)
    if len(hull) < 3 or not data.line:
        return

    colour = _argb_to_rgba(data.line[0].style.background_primary_color)
    pad = int(round(thinnest * padding)) if thinnest != float("inf") else 0

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.polygon(hull, fill=colour)
    if pad > 0:
        # Widening the outline with a thick round-jointed line grows the shape
        # by `pad` in every direction and rounds its corners in one step.
        draw.line(hull + [hull[0]], fill=colour, width=pad * 2, joint="curve")
        for x, y in hull:
            draw.ellipse((x - pad, y - pad, x + pad, y + pad), fill=colour)
    canvas.alpha_composite(layer)


def _is_upright(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _UPRIGHT_RANGES)


# Vertical Japanese typography: a few characters do not simply stack.
# Small punctuation sits in the upper-right of its em square rather than the
# centre, and dashes and brackets are rotated a quarter turn.
_VERTICAL_CORNER_PUNCT = frozenset("、。，．")
_VERTICAL_ROTATED_PUNCT = frozenset(
    "ー―‐—–〜~（）()「」『』【】〔〕［］[]｛｝{}〈〉《》…‥"
)

# Languages whose scripts read comfortably in vertical columns. Everything else
# is better reflowed horizontally.
_CJK_LANGUAGES = frozenset({"ja", "zh", "ko", "yue", "zh-cn", "zh-tw", "zh-hk"})


def should_reflow_horizontally(vertical_text: str, target_language: str) -> bool:
    """Decide whether vertical source text should be laid out horizontally.

    "auto" keeps vertical only when the translation is itself a CJK language;
    Russian or English set in a vertical column is technically faithful to the
    source and miserable to read.
    """
    if vertical_text == "horizontal":
        return True
    if vertical_text != "auto":
        return False
    target = (target_language or "").lower()
    return not (target in _CJK_LANGUAGES or target.split("-")[0] in _CJK_LANGUAGES)


def _vertical_runs(text: str) -> List[Tuple[bool, str]]:
    """Split text into upright (CJK) and sideways (Latin) runs.

    Whitespace joins whichever run precedes it so a space between two kanji does
    not start a sideways run of its own.
    """
    runs: List[Tuple[bool, str]] = []
    for char in text:
        upright = _is_upright(char)
        if char.isspace() and runs:
            upright = runs[-1][0]
        if runs and runs[-1][0] == upright:
            runs[-1] = (upright, runs[-1][1] + char)
        else:
            runs.append((upright, char))
    return runs


def _measure_vertical(text: str, font: ImageFont.FreeTypeFont) -> Tuple[float, float]:
    """Column width and total height of `text` set vertically."""
    ascent, descent = font.getmetrics()
    em = ascent + descent
    width = 0.0
    height = 0.0
    for upright, run in _vertical_runs(text):
        if upright:
            # Each glyph occupies one em of column height.
            height += em * len(run)
            width = max(width, max(font.getlength(ch) for ch in run))
        else:
            # A sideways run is as tall as it is long, and one em thick.
            height += font.getlength(run)
            width = max(width, float(em))
    return width, height


def fit_font_size_vertical(
    text: str, font_path: Optional[str], box_width: float, box_height: float
) -> Tuple[ImageFont.FreeTypeFont, int]:
    """fit_font_size for a vertical column: width is the constraint, not length."""
    cache: dict = {}

    def load(size: int) -> ImageFont.FreeTypeFont:
        if size not in cache:
            cache[size] = (
                ImageFont.truetype(font_path, size)
                if font_path
                else ImageFont.load_default(size)
            )
        return cache[size]

    low, high = RENDER_MIN_FONT_SIZE, RENDER_MAX_FONT_SIZE
    while low <= high:
        mid = (low + high) // 2
        width, height = _measure_vertical(text, load(mid))
        if width >= box_width or height >= box_height:
            high = mid - 1
        else:
            low = mid + 1

    size = max(RENDER_MIN_FONT_SIZE, min(low - 1, RENDER_MAX_FONT_SIZE))
    return load(size), size


def _render_vertical_tile(
    text: str,
    font: ImageFont.FreeTypeFont,
    box_w: float,
    box_h: float,
    fill: Tuple[int, int, int, int],
    outline: int,
    outline_color: Optional[Tuple[int, int, int, int]],
    align: str,
) -> Image.Image:
    """Set text top-to-bottom in a narrow column, CJK glyphs upright.

    This is CSS writing-mode: vertical-* with the default text-orientation:
    mixed - ideographs stand up and stack, Latin runs lie on their side rotated
    90 degrees clockwise.
    """
    tile_w, tile_h = max(1, round(box_w)), max(1, round(box_h))
    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    ascent, descent = font.getmetrics()
    em = ascent + descent

    _, total_h = _measure_vertical(text, font)
    # Vertical alignment is the "start/center/end" of the column.
    y = {
        "left": 0.0,
        "center": (box_h - total_h) / 2,
        "right": box_h - total_h,
    }.get(align, (box_h - total_h) / 2)

    def stamp(target: ImageDraw.ImageDraw, px: float, py: float, glyph: str):
        # Pillow strokes text natively. Chromium uses four offset copies only
        # because CSS has no portable text stroke, and that reads as an outline
        # only while the offset is a pixel or two - past that the copies
        # separate into ghosts with gaps between them.
        target.text(
            (px, py),
            glyph,
            font=font,
            fill=fill,
            stroke_width=outline if outline_color else 0,
            stroke_fill=outline_color,
        )

    for upright, run in _vertical_runs(text):
        if upright:
            for char in run:
                advance = font.getlength(char)
                if char in _VERTICAL_ROTATED_PUNCT:
                    # Dashes and brackets turn a quarter turn in vertical text.
                    pad = 2 * outline + 2
                    sub = Image.new(
                        "RGBA", (max(1, round(advance) + pad), em + pad), (0, 0, 0, 0)
                    )
                    stamp(ImageDraw.Draw(sub), pad / 2, pad / 2, char)
                    sub = sub.rotate(-90, expand=True)
                    tile.alpha_composite(
                        sub, (round((box_w - sub.width) / 2), round(y - pad / 2))
                    )
                elif char in _VERTICAL_CORNER_PUNCT:
                    # Kuten and touten hang in the upper right of the em square.
                    stamp(
                        draw, (box_w - advance) / 2 + advance * 0.45, y - em * 0.4, char
                    )
                else:
                    stamp(draw, (box_w - advance) / 2, y, char)
                y += em
        else:
            run_len = font.getlength(run)
            if run_len <= 0:
                continue
            pad = 2 * outline + 2
            sub = Image.new(
                "RGBA", (max(1, round(run_len) + pad), em + pad), (0, 0, 0, 0)
            )
            stamp(ImageDraw.Draw(sub), pad / 2, pad / 2, run)
            sub = sub.rotate(-90, expand=True)
            tile.alpha_composite(
                sub, (round((box_w - sub.width) / 2), round(y - pad / 2))
            )
            y += run_len
    return tile


def font_for_text(text: str, preferred: Optional[str]) -> Optional[str]:
    """Pick a font that actually has glyphs for this line.

    Pillow binds one font file per face, so a Japanese font asked to draw
    Simplified Chinese silently emits tofu. The resolver keeps `preferred`
    whenever it covers the text, so an explicit --font is never overridden for
    no reason.
    """
    try:
        from ..utils.font_fallback import resolve_font_for_text
    except ImportError:  # pragma: no cover - resolver is optional
        return preferred
    try:
        return resolve_font_for_text(text, preferred) or preferred
    except Exception as e:  # pragma: no cover - never fail a render over fonts
        logger.debug("Font fallback failed, using the configured font: %s", e)
        return preferred


def _wrap_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
    per_character: bool = False,
) -> List[str]:
    """Greedy wrap, breaking between words or between characters.

    Which of the two applies is a property of the *language*, not of the string
    in hand. Deciding it from whether the text happened to contain a space split
    short words - a one-word Russian bubble came out stacked letter by letter.
    """
    lines: List[str] = []
    for hard_line in text.splitlines() or [""]:
        if not hard_line:
            lines.append("")
            continue

        tokens = list(hard_line) if per_character else hard_line.split()
        joiner = "" if per_character else " "

        current = ""
        for token in tokens:
            candidate = f"{current}{joiner}{token}" if current else token
            if font.getlength(candidate) <= max_width or not current:
                current = candidate
            else:
                lines.append(current)
                current = token
        if current:
            lines.append(current)
    return lines


def wraps_per_character(target_language: str) -> bool:
    """ja, zh and ko break between characters; everything else between words."""
    base = (target_language or "").split("-")[0].lower()
    return base in _CJK_LANGUAGES or target_language.lower() in _CJK_LANGUAGES


def fit_text_block(
    text: str,
    font_path: Optional[str],
    box_w: float,
    box_h: float,
    per_character: bool = False,
) -> Tuple[ImageFont.FreeTypeFont, int, List[str]]:
    """Largest font at which `text` wraps to fit inside the box.

    Used when reflowing a vertical paragraph into horizontal lines: unlike
    Chromium's per-line fit, here the text genuinely has to be re-wrapped,
    because the source line boxes are tall columns that horizontal text cannot
    sensibly occupy.
    """
    cache: dict = {}

    def load(size: int) -> ImageFont.FreeTypeFont:
        if size not in cache:
            cache[size] = (
                ImageFont.truetype(font_path, size)
                if font_path
                else ImageFont.load_default(size)
            )
        return cache[size]

    low, high = RENDER_MIN_FONT_SIZE, RENDER_MAX_FONT_SIZE
    best: List[str] = []
    while low <= high:
        mid = (low + high) // 2
        font = load(mid)
        ascent, descent = font.getmetrics()
        lines = _wrap_text(text, font, box_w, per_character)
        total_h = len(lines) * (ascent + descent)
        widest = max((font.getlength(ln) for ln in lines), default=0.0)
        if widest >= box_w or total_h >= box_h:
            high = mid - 1
        else:
            low = mid + 1
            best = lines

    size = max(RENDER_MIN_FONT_SIZE, min(low - 1, RENDER_MAX_FONT_SIZE))
    font = load(size)
    return font, size, best or _wrap_text(text, font, box_w, per_character)


def _render_text_block(
    lines: List[str],
    font: ImageFont.FreeTypeFont,
    box_w: float,
    box_h: float,
    fill: Tuple[int, int, int, int],
    outline: int,
    outline_color: Optional[Tuple[int, int, int, int]],
    align: str,
) -> Image.Image:
    """Draw pre-wrapped horizontal lines centred in a box."""
    tile = Image.new("RGBA", (max(1, round(box_w)), max(1, round(box_h))), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    ascent, descent = font.getmetrics()
    em = ascent + descent

    y = (box_h - len(lines) * em) / 2
    for line in lines:
        advance = font.getlength(line)
        x = {
            "left": 0.0,
            "center": (box_w - advance) / 2,
            "right": box_w - advance,
        }.get(align, (box_w - advance) / 2)
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=outline if outline_color else 0,
            stroke_fill=outline_color,
        )
        y += em
    return tile


def _paste_rotated(
    canvas: Image.Image, tile: Image.Image, cx: float, cy: float, deg: float
):
    if deg:
        tile = tile.rotate(deg, expand=True, resample=Image.Resampling.BICUBIC)
    canvas.alpha_composite(
        tile, (round(cx - tile.width / 2), round(cy - tile.height / 2))
    )


def _draw_background(
    canvas: Image.Image,
    tline: Any,
    box_w: float,
    box_h: float,
    cx: float,
    cy: float,
    deg: float,
    aspect: float,
) -> bool:
    """Paint the inpainted patch, or a flat fill when the server sent none.

    Returns True when the real inpainted patch was used, which also decides
    whether the text gets an outline.
    """
    if tline.HasField("background_image_data"):
        bgd = tline.background_image_data
        # Both paddings are expressed as fractions of the LINE HEIGHT. The
        # horizontal one is divided by the image aspect ratio to convert it into
        # a fraction of the width; skipping that makes the patch wildly too wide.
        pad_w = bgd.horizontal_padding * box_h / aspect
        pad_h = bgd.vertical_padding * box_h
        patch_w = max(1, round(box_w + pad_w))
        patch_h = max(1, round(box_h + pad_h))
        try:
            patch = Image.open(io.BytesIO(bgd.background_image)).convert("RGBA")
            # Bilinear, not Lanczos: the patch is a small, heavily compressed
            # WebP and sharper filters ring around the erased glyphs.
            patch = patch.resize((patch_w, patch_h), Image.Resampling.BILINEAR)
            _paste_rotated(canvas, patch, cx, cy, deg)
            return True
        except Exception as e:
            logger.debug("Could not decode inpainted background: %s", e)

    fill = Image.new(
        "RGBA",
        (max(1, round(box_w) + 4), max(1, round(box_h) + 2)),
        _argb_to_rgba(tline.style.background_primary_color),
    )
    _paste_rotated(canvas, fill, cx, cy, deg)
    return False


def render_translation_overlay(
    image: Image.Image,
    objects_response: "LensOverlayObjectsResponse",
    font_path: Optional[str] = None,
    draw_background: bool = True,
    vertical_text: str = "auto",
    erase_mode: str = "patch",
    hull_padding: float = 0.45,
    outline_scale: float = 1.0,
    min_readable_px: float = 0.0,
    text_align: str = "auto",
    manga_mode: bool = False,
    manga_box_growth: float = 1.45,
) -> Image.Image:
    """Repaint translated text onto the image, Chromium-style.

    Each translated line reuses the geometry of the ORIGINAL detected line -
    the server sends no geometry for translated text - so the two must line up
    index for index, which is also how Chromium validates the response.

    `vertical_text` controls what happens to top-to-bottom source text:
      "keep"       - render it vertically, as Chromium does.
      "auto"       - reflow only when the target language is not CJK.
      "horizontal" - reflow the whole paragraph into horizontal wrapped lines.
                     Vertical Japanese translated into Russian or English is
                     painful to read set vertically, and the source line boxes
                     are tall narrow columns that horizontal text cannot occupy,
                     so the paragraph box is used as one text area instead.

    `erase_mode` chooses how the source is removed:
      "patch" - the server's inpainted patches, as Chromium does. Faithful, but
                it erases glyphs while keeping their anti-aliased edges, and on
                a page of vertical text that residue reads as noise.
      "hull"  - cover the convex hull of the line boxes with the line's
                background colour. Only right where that colour is flat, which
                inside a speech bubble it is.

    `min_readable_px` raises text that would otherwise render too small to read:
    Lens fits text to the original line box, so fine print on a large page comes
    back at a few pixels. Lines can then overlap, which is why it is optional.

    `manga_mode` bundles the settings a page of vertical Japanese wants: always
    reflow, lay out wider than the detected box, erase by hull, and a floor of
    at least 14px.
    """
    if manga_mode:
        vertical_text = "horizontal"
        erase_mode = "hull"
        min_readable_px = max(min_readable_px, 14.0)

    canvas = image.convert("RGBA")
    width, height = canvas.size
    aspect = width / height

    paragraphs = objects_response.text.text_layout.paragraphs
    gleams = objects_response.deep_gleams
    rendered_lines = 0

    for index, paragraph in enumerate(paragraphs):
        if index >= len(gleams):
            break
        gleam = gleams[index]
        if not gleam.HasField("translation"):
            continue

        data = gleam.translation
        if data.status.code != _TRANSLATION_STATUS_SUCCESS:
            continue
        if len(data.line) != len(paragraph.lines):
            # Chromium drops the paragraph in this case rather than guessing.
            logger.debug(
                "Paragraph %d: %d detected lines vs %d translated, skipping.",
                index,
                len(paragraph.lines),
                len(data.line),
            )
            continue

        vertical = data.writing_direction == _WRITING_DIRECTION_TOP_TO_BOTTOM
        is_rtl = (
            data.writing_direction == _WRITING_DIRECTION_RTL
            or data.target_language.split("-")[0].lower() in RTL_LANGUAGES
        )
        # Chromium always follows the source. Once text has been reflowed into a
        # shape the source never had, that stops being obviously right.
        if text_align != "auto":
            align = text_align
        else:
            align = _ALIGNMENT.get(data.alignment, "center")
            if is_rtl and align == "left":
                align = "right"

        use_hull = draw_background and erase_mode == "hull"
        if use_hull:
            _erase_text_area(canvas, paragraph, data, hull_padding)

        reflow = vertical and should_reflow_horizontally(
            vertical_text, data.target_language
        )
        if reflow and paragraph.HasField("geometry"):
            # Erase the source columns first, then lay the whole paragraph out
            # as one horizontal text area over the paragraph's own box.
            style = data.line[0].style if data.line else None
            has_inpaint = False
            for line_index, tline in enumerate(data.line):
                box = paragraph.lines[line_index].geometry.bounding_box
                box_w, box_h = box.width * width, box.height * height
                if box_w < 1 or box_h < 1 or not draw_background:
                    continue
                has_inpaint |= _draw_background(
                    canvas,
                    tline,
                    box_w,
                    box_h,
                    box.center_x * width,
                    box.center_y * height,
                    -math.degrees(box.rotation_z),
                    aspect,
                )

            pbox = paragraph.geometry.bounding_box
            # The detected box hugs the glyphs. A speech bubble is round and has
            # room around them, so manga mode lays out wider than the box.
            growth = max(1.0, manga_box_growth) if manga_mode else 1.0
            pw = pbox.width * width * growth
            ph = pbox.height * height * min(growth, 1.2)
            text = shape_for_display(data.translation.strip(), is_rtl)
            if pw >= 1 and ph >= 1 and text:
                text_color = (
                    _argb_to_rgba(style.text_color) if style else (0, 0, 0, 255)
                )
                outline_color = (
                    _argb_to_rgba(style.background_primary_color)
                    if ((has_inpaint or use_hull) and style)
                    else None
                )
                line_font = font_for_text(text, font_path)
                font, font_size, lines = fit_text_block(
                    text, line_font, pw, ph, wraps_per_character(data.target_language)
                )
                floor = int(round(min_readable_px))
                if floor > font_size:
                    font = _load_font(line_font, floor)
                    font_size = floor
                    lines = _wrap_text(
                        text, font, pw, wraps_per_character(data.target_language)
                    )
                tile = _render_text_block(
                    lines,
                    font,
                    pw,
                    ph,
                    text_color,
                    (
                        max(1, round(font_size * RENDER_OUTLINE_RATIO))
                        if outline_color
                        else 0
                    ),
                    outline_color,
                    align,
                )
                _paste_rotated(
                    canvas,
                    tile,
                    pbox.center_x * width,
                    pbox.center_y * height,
                    -math.degrees(pbox.rotation_z),
                )
                rendered_lines += len(lines)
            continue

        for line_index, tline in enumerate(data.line):
            box = paragraph.lines[line_index].geometry.bounding_box
            box_w, box_h = box.width * width, box.height * height
            if box_w < 1 or box_h < 1:
                continue

            # Pillow rotates counter-clockwise; rotation_z is clockwise.
            deg = -math.degrees(box.rotation_z)
            cx, cy = box.center_x * width, box.center_y * height

            has_inpaint = False
            if draw_background and not use_hull:
                has_inpaint = _draw_background(
                    canvas, tline, box_w, box_h, cx, cy, deg, aspect
                )
            elif use_hull:
                # The hull already covers the source; the outline still helps.
                has_inpaint = True

            next_line = (
                data.line[line_index + 1] if line_index + 1 < len(data.line) else None
            )
            text = build_line_text(data.translation, tline, next_line)
            if not text.strip():
                continue
            text = shape_for_display(text, is_rtl)

            text_color = _argb_to_rgba(tline.style.text_color)
            # The outline keeps the text legible over whatever residue the
            # inpainting left behind; with a flat fill there is nothing to hide.
            outline_color = (
                _argb_to_rgba(tline.style.background_primary_color)
                if has_inpaint
                else None
            )

            line_font = font_for_text(text, font_path)
            floor = int(round(min_readable_px))
            if vertical:
                font, font_size = fit_font_size_vertical(text, line_font, box_w, box_h)
                outline = (
                    max(1, round(font_size * RENDER_OUTLINE_RATIO))
                    if outline_color
                    else 0
                )
                tile = _render_vertical_tile(
                    text,
                    font,
                    box_w,
                    box_h,
                    text_color,
                    outline,
                    outline_color,
                    align,
                )
            else:
                font, font_size = fit_font_size(text, line_font, box_w, box_h)
                if floor > font_size:
                    font, font_size = _load_font(line_font, floor), floor
                advance = font.getlength(text)
                ascent, descent = font.getmetrics()

                tile = Image.new(
                    "RGBA", (max(1, round(box_w)), max(1, round(box_h))), (0, 0, 0, 0)
                )
                draw = ImageDraw.Draw(tile)
                x = {
                    "left": 0.0,
                    "center": (box_w - advance) / 2,
                    "right": box_w - advance,
                }[align]
                y = (box_h - (ascent + descent)) / 2

                outline = (
                    max(1, round(font_size * RENDER_OUTLINE_RATIO * outline_scale))
                    if outline_color
                    else 0
                )
                draw.text(
                    (x, y),
                    text,
                    font=font,
                    fill=text_color,
                    stroke_width=outline,
                    stroke_fill=outline_color,
                )

            _paste_rotated(canvas, tile, cx, cy, deg)
            rendered_lines += 1

    logger.debug("Rendered %d translated lines.", rendered_lines)
    return canvas
