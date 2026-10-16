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

Layout is split across modules: fonts and measuring in ``render_fonts``,
vertical columns in ``render_vertical``, shared drawing helpers in
``render_common``. This one reads the response and drives them.
"""

import io
import logging
import math
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, List, Optional, Tuple, Union

from PIL import Image, ImageDraw, features

from ..constants import (
    RENDER_MAX_FONT_SIZE,
    RENDER_MIN_FONT_SIZE,
    RTL_LANGUAGES,
)
from .render_common import composite, outline_px
from .render_fonts import FontPlan, SizedPlan
from .render_vertical import (  # noqa: F401 - re-exported for callers and tests
    _UPRIGHT_RANGES,
    _VERTICAL_CORNER_PUNCT,
    _VERTICAL_ROTATED_PUNCT,
    fit_font_size_vertical,
    glyph_for,
    is_upright,
    measure_vertical,
    render_vertical_tile,
    vertical_runs,
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

# The names the vertical code had when it lived in this module.
_is_upright = is_upright
_vertical_runs = vertical_runs
_measure_vertical = measure_vertical


def _argb_to_rgba(value: int) -> Tuple[int, int, int, int]:
    """Convert the server's aRGB uint32 into Pillow's RGBA tuple."""
    return (
        (value >> 16) & 0xFF,
        (value >> 8) & 0xFF,
        value & 0xFF,
        (value >> 24) & 0xFF,
    )


@lru_cache(maxsize=8)
def _utf16(text: str) -> bytes:
    return text.encode("utf-16-le")


def _u16_slice(text: str, start: int, end: int) -> str:
    """Slice by UTF-16 code units.

    The server's word offsets are what icu::UnicodeString uses, which indexes
    UTF-16 code units. Python strings index code points, so anything outside the
    BMP (emoji, rare CJK) would drift if we sliced directly.

    The encoded form is cached: a paragraph is sliced twice per word, and
    re-encoding the whole translation each time is quadratic in its length.
    """
    if start >= end:
        return ""
    return _utf16(text)[2 * start : 2 * end].decode("utf-16-le", errors="replace")


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


FontSpec = Union[str, FontPlan, None]


def _as_plan(font: FontSpec) -> FontPlan:
    return font if isinstance(font, FontPlan) else FontPlan.fixed(font)


def fit_font_size(
    text: str, font: FontSpec, box_width: float, box_height: float
) -> Tuple[SizedPlan, int]:
    """Largest font size whose text fits the line box, by binary search.

    This is calculateFontSizePixels(). Two details matter and are easy to get
    wrong: the height test uses the font's bounding box (ascent + descent), not
    the ink extents of these particular glyphs, and the comparison is strictly
    "greater or equal fails", so the winning size always leaves a little slack.
    Chromium never wraps a translated line - it scales the text down instead.

    `font` is a path (or None for the default font) or a FontPlan. The font that
    comes back is a SizedPlan: it measures and draws like a Pillow font but may
    span several faces.
    """
    plan = _as_plan(font)
    low, high = RENDER_MIN_FONT_SIZE, RENDER_MAX_FONT_SIZE
    while low <= high:
        mid = (low + high) // 2
        sized = plan.at(mid)
        ascent, descent = sized.getmetrics()
        if sized.getlength(text) >= box_width or (ascent + descent) >= box_height:
            high = mid - 1
        else:
            low = mid + 1

    size = max(RENDER_MIN_FONT_SIZE, min(low - 1, RENDER_MAX_FONT_SIZE))
    return plan.at(size), size


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

    The shape depends only on the detected line boxes. Nothing about how the
    translation is later drawn - its size, a readable-size floor, an outline -
    may feed back into it: sizing the erased area from drawn text is what once
    painted black bars across a page.
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

    # Work in a layer just big enough for the shape. A full-canvas layer per
    # paragraph makes the cost of a busy page grow with image size times
    # paragraphs. The origin is a whole pixel so rasterisation is unchanged.
    margin = pad + 2
    x0 = max(0, math.floor(min(x for x, _ in hull)) - margin)
    y0 = max(0, math.floor(min(y for _, y in hull)) - margin)
    x1 = min(width, math.ceil(max(x for x, _ in hull)) + margin)
    y1 = min(height, math.ceil(max(y for _, y in hull)) + margin)
    if x1 <= x0 or y1 <= y0:
        return
    local = [(x - x0, y - y0) for x, y in hull]

    layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.polygon(local, fill=colour)
    if pad > 0:
        # Widening the outline with a thick round-jointed line grows the shape
        # by `pad` in every direction and rounds its corners in one step.
        draw.line(local + [local[0]], fill=colour, width=pad * 2, joint="curve")
        for x, y in local:
            draw.ellipse((x - pad, y - pad, x + pad, y + pad), fill=colour)
    composite(canvas, layer, x0, y0)


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


def font_for_text(text: str, preferred: Optional[str]) -> Optional[str]:
    """Pick a font file that actually has glyphs for this line.

    Pillow binds one font file per face, so a Japanese font asked to draw
    Simplified Chinese silently emits tofu. The resolver keeps `preferred`
    whenever it covers the text, so an explicit --font is never overridden for
    no reason.

    This returns a path only. The renderer itself works with a ``FontPlan``,
    which keeps the face index of a collection and falls back per run when no
    single font covers a mixed-script line.
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
    font: Any,
    max_width: float,
    per_character: bool = False,
) -> List[str]:
    """Greedy wrap, breaking between words or between characters.

    `font` is anything with ``getlength`` - a Pillow font or a SizedPlan.

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
    font: FontSpec,
    box_w: float,
    box_h: float,
    per_character: bool = False,
) -> Tuple[SizedPlan, int, List[str]]:
    """Largest font at which `text` wraps to fit inside the box.

    Used when reflowing a vertical paragraph into horizontal lines: unlike
    Chromium's per-line fit, here the text genuinely has to be re-wrapped,
    because the source line boxes are tall columns that horizontal text cannot
    sensibly occupy.
    """
    plan = _as_plan(font)
    low, high = RENDER_MIN_FONT_SIZE, RENDER_MAX_FONT_SIZE
    best: List[str] = []
    while low <= high:
        mid = (low + high) // 2
        sized = plan.at(mid)
        ascent, descent = sized.getmetrics()
        lines = _wrap_text(text, sized, box_w, per_character)
        total_h = len(lines) * (ascent + descent)
        widest = max((sized.getlength(ln) for ln in lines), default=0.0)
        if widest >= box_w or total_h >= box_h:
            high = mid - 1
        else:
            low = mid + 1
            best = lines

    size = max(RENDER_MIN_FONT_SIZE, min(low - 1, RENDER_MAX_FONT_SIZE))
    sized = plan.at(size)
    return sized, size, best or _wrap_text(text, sized, box_w, per_character)


def _align_x(align: str, box_w: float, advance: float) -> float:
    return {
        "left": 0.0,
        "center": (box_w - advance) / 2,
        "right": box_w - advance,
    }.get(align, (box_w - advance) / 2)


def _render_text_block(
    lines: List[str],
    font: SizedPlan,
    box_w: float,
    box_h: float,
    fill: Tuple[int, int, int, int],
    outline: int,
    outline_color: Optional[Tuple[int, int, int, int]],
    align: str,
    grow: bool = False,
) -> Image.Image:
    """Draw pre-wrapped horizontal lines centred in a box.

    With `grow`, a block larger than its box gets a tile big enough to hold it
    (see ``render_vertical_tile``) instead of being clipped to the box.
    """
    ascent, descent = font.getmetrics()
    em = ascent + descent
    tile_w, tile_h = max(1, round(box_w)), max(1, round(box_h))
    ox = oy = 0.0
    if grow:
        edge = 2 * outline + 2
        widest = max((font.getlength(line) for line in lines), default=0.0)
        need_w, need_h = math.ceil(widest) + edge, len(lines) * em + edge
        if need_w > tile_w:
            tile_w = need_w
            ox = (tile_w - box_w) / 2
        if need_h > tile_h:
            tile_h = need_h
            oy = (tile_h - box_h) / 2

    tile = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)

    y = oy + (box_h - len(lines) * em) / 2
    for line in lines:
        advance = font.getlength(line)
        font.draw(
            draw,
            (ox + _align_x(align, box_w, advance), y),
            line,
            fill,
            stroke_width=outline if outline_color else 0,
            stroke_fill=outline_color,
        )
        y += em
    return tile


def _render_line_tile(
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
    """One horizontal line, vertically centred in its box."""
    return _render_text_block(
        [text], font, box_w, box_h, fill, outline, outline_color, align, grow
    )


def _paste_rotated(
    canvas: Image.Image, tile: Image.Image, cx: float, cy: float, deg: float
):
    if deg:
        tile = tile.rotate(deg, expand=True, resample=Image.Resampling.BICUBIC)
    composite(canvas, tile, round(cx - tile.width / 2), round(cy - tile.height / 2))


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


@dataclass
class _Scene:
    """The canvas being painted and the settings that apply to all of it."""

    canvas: Image.Image
    font_path: Optional[str]
    draw_background: bool
    vertical_text: str
    erase_mode: str
    hull_padding: float
    outline_scale: float
    min_readable_px: float
    text_align: str
    manga_mode: bool
    manga_box_growth: float

    def __post_init__(self):
        self.width, self.height = self.canvas.size
        self.aspect = self.width / self.height

    @property
    def floor(self) -> int:
        """The readable-size floor in whole pixels, 0 when off."""
        return min(int(round(self.min_readable_px)), RENDER_MAX_FONT_SIZE)


def _paragraph_alignment(scene: _Scene, data, is_rtl: bool) -> str:
    # Chromium always follows the source. Once text has been reflowed into a
    # shape the source never had, that stops being obviously right.
    if scene.text_align != "auto":
        return scene.text_align
    align = _ALIGNMENT.get(data.alignment, "center")
    if is_rtl and align == "left":
        align = "right"
    return align


def _render_reflow_paragraph(
    scene: _Scene, paragraph, data, align: str, is_rtl: bool, use_hull: bool
) -> int:
    """Lay a whole vertical paragraph out as horizontal wrapped lines.

    The source columns are erased first - by the hull when `use_hull`, else by
    the server's patches - and the translation is then set as one text area over
    the paragraph's own box. Returns the number of lines drawn.
    """
    canvas, width, height = scene.canvas, scene.width, scene.height
    style = data.line[0].style if data.line else None

    has_inpaint = False
    # When the hull was used it already covers the source. Painting the patches
    # on top of it would put the residue back that the hull exists to remove.
    if not use_hull:
        for line_index, tline in enumerate(data.line):
            box = paragraph.lines[line_index].geometry.bounding_box
            box_w, box_h = box.width * width, box.height * height
            if box_w < 1 or box_h < 1 or not scene.draw_background:
                continue
            has_inpaint |= _draw_background(
                canvas,
                tline,
                box_w,
                box_h,
                box.center_x * width,
                box.center_y * height,
                -math.degrees(box.rotation_z),
                scene.aspect,
            )

    pbox = paragraph.geometry.bounding_box
    # The detected box hugs the glyphs. A speech bubble is round and has room
    # around them, so manga mode lays out wider than the box.
    growth = max(1.0, scene.manga_box_growth) if scene.manga_mode else 1.0
    pw = pbox.width * width * growth
    ph = pbox.height * height * min(growth, 1.2)
    text = shape_for_display(data.translation.strip(), is_rtl)
    if not (pw >= 1 and ph >= 1 and text):
        return 0

    text_color = _argb_to_rgba(style.text_color) if style else (0, 0, 0, 255)
    outline_color = (
        _argb_to_rgba(style.background_primary_color)
        if ((has_inpaint or use_hull) and style)
        else None
    )
    per_character = wraps_per_character(data.target_language)
    plan = FontPlan.resolve(text, scene.font_path)
    font, font_size, lines = fit_text_block(text, plan, pw, ph, per_character)
    floored = scene.floor > font_size
    if floored:
        font = plan.at(scene.floor)
        font_size = scene.floor
        lines = _wrap_text(text, font, pw, per_character)

    tile = _render_text_block(
        lines,
        font,
        pw,
        ph,
        text_color,
        outline_px(font_size, scene.outline_scale) if outline_color else 0,
        outline_color,
        align,
        grow=floored,
    )
    _paste_rotated(
        canvas,
        tile,
        pbox.center_x * width,
        pbox.center_y * height,
        -math.degrees(pbox.rotation_z),
    )
    return len(lines)


def _render_vertical(
    scene: _Scene,
    text: str,
    plan: FontPlan,
    box_w: float,
    box_h: float,
    text_color,
    outline_color,
    align: str,
) -> Image.Image:
    """One top-to-bottom column, fitted to its box and floored if asked."""
    font, font_size = fit_font_size_vertical(text, plan, box_w, box_h)
    floored = scene.floor > font_size
    if floored:
        font, font_size = plan.at(scene.floor), scene.floor
    return render_vertical_tile(
        text,
        font,
        box_w,
        box_h,
        text_color,
        outline_px(font_size, scene.outline_scale) if outline_color else 0,
        outline_color,
        align,
        grow=floored,
    )


def _render_horizontal(
    scene: _Scene,
    text: str,
    plan: FontPlan,
    box_w: float,
    box_h: float,
    text_color,
    outline_color,
    align: str,
) -> Image.Image:
    """One left-to-right line, fitted to its box and floored if asked."""
    font, font_size = fit_font_size(text, plan, box_w, box_h)
    floored = scene.floor > font_size
    if floored:
        font, font_size = plan.at(scene.floor), scene.floor
    return _render_line_tile(
        text,
        font,
        box_w,
        box_h,
        text_color,
        outline_px(font_size, scene.outline_scale) if outline_color else 0,
        outline_color,
        align,
        grow=floored,
    )


def _render_line(
    scene: _Scene,
    paragraph,
    data,
    line_index: int,
    vertical: bool,
    is_rtl: bool,
    align: str,
    use_hull: bool,
) -> bool:
    """Erase and repaint one detected line. Returns True when text was drawn."""
    tline = data.line[line_index]
    box = paragraph.lines[line_index].geometry.bounding_box
    box_w, box_h = box.width * scene.width, box.height * scene.height
    if box_w < 1 or box_h < 1:
        return False

    # Pillow rotates counter-clockwise; rotation_z is clockwise.
    deg = -math.degrees(box.rotation_z)
    cx, cy = box.center_x * scene.width, box.center_y * scene.height

    has_inpaint = False
    if scene.draw_background and not use_hull:
        has_inpaint = _draw_background(
            scene.canvas, tline, box_w, box_h, cx, cy, deg, scene.aspect
        )
    elif use_hull:
        # The hull already covers the source; the outline still helps.
        has_inpaint = True

    next_line = data.line[line_index + 1] if line_index + 1 < len(data.line) else None
    text = build_line_text(data.translation, tline, next_line)
    if not text.strip():
        return False
    text = shape_for_display(text, is_rtl)

    text_color = _argb_to_rgba(tline.style.text_color)
    # The outline keeps the text legible over whatever residue the inpainting
    # left behind; with a flat fill there is nothing to hide.
    outline_color = (
        _argb_to_rgba(tline.style.background_primary_color) if has_inpaint else None
    )

    plan = FontPlan.resolve(text, scene.font_path)
    draw_tile = _render_vertical if vertical else _render_horizontal
    tile = draw_tile(scene, text, plan, box_w, box_h, text_color, outline_color, align)
    _paste_rotated(scene.canvas, tile, cx, cy, deg)
    return True


def _render_paragraph(scene: _Scene, index: int, paragraph, data) -> int:
    """Paint one translated paragraph. Returns how many lines were drawn."""
    if len(data.line) != len(paragraph.lines):
        # Chromium drops the paragraph in this case rather than guessing.
        logger.debug(
            "Paragraph %d: %d detected lines vs %d translated, skipping.",
            index,
            len(paragraph.lines),
            len(data.line),
        )
        return 0

    vertical = data.writing_direction == _WRITING_DIRECTION_TOP_TO_BOTTOM
    is_rtl = (
        data.writing_direction == _WRITING_DIRECTION_RTL
        or data.target_language.split("-")[0].lower() in RTL_LANGUAGES
    )
    align = _paragraph_alignment(scene, data, is_rtl)

    use_hull = scene.draw_background and scene.erase_mode == "hull"
    if use_hull:
        _erase_text_area(scene.canvas, paragraph, data, scene.hull_padding)

    reflow = vertical and should_reflow_horizontally(
        scene.vertical_text, data.target_language
    )
    if reflow and paragraph.HasField("geometry"):
        return _render_reflow_paragraph(scene, paragraph, data, align, is_rtl, use_hull)

    return sum(
        _render_line(
            scene, paragraph, data, line_index, vertical, is_rtl, align, use_hull
        )
        for line_index in range(len(data.line))
    )


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
                inside a speech bubble it is. The patches are then not drawn at
                all, in the per-line layout and the reflowed one alike.

    `outline_scale` multiplies the outline around the text; 0 removes it.

    `min_readable_px` raises text that would otherwise render too small to read:
    Lens fits text to the original line box, so fine print on a large page comes
    back at a few pixels. Lines can then overlap, which is why it is optional.
    The erased area never grows with it - only the text does, and the tile that
    holds it is sized to the text as measured.

    `manga_mode` bundles the settings a page of vertical Japanese wants: always
    reflow, lay out wider than the detected box, erase by hull, and a floor of
    at least 14px.

    Text is set in `font_path` wherever it has the glyphs. A line it does not
    cover is drawn in the best installed font for each script it contains, with
    the right regional face for CJK.
    """
    if manga_mode:
        vertical_text = "horizontal"
        erase_mode = "hull"
        min_readable_px = max(min_readable_px, 14.0)

    scene = _Scene(
        canvas=image.convert("RGBA"),
        font_path=font_path,
        draw_background=draw_background,
        vertical_text=vertical_text,
        erase_mode=erase_mode,
        hull_padding=hull_padding,
        outline_scale=outline_scale,
        min_readable_px=min_readable_px,
        text_align=text_align,
        manga_mode=manga_mode,
        manga_box_growth=manga_box_growth,
    )

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

        rendered_lines += _render_paragraph(scene, index, paragraph, data)

    logger.debug("Rendered %d translated lines.", rendered_lines)
    return scene.canvas
