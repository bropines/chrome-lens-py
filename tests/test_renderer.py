"""Offline tests for the Chromium-style translation renderer.

Nothing here talks to the network. A synthetic ``LensOverlayObjectsResponse`` is
built the way the server shapes one - paragraphs of detected lines, plus one
translation per paragraph whose lines reuse the source geometry - and fed to
``render_translation_overlay`` exactly as ``LensAPI`` does.
"""

import hashlib
import io
import math
import sys
from typing import List, Optional, Sequence, Tuple

import pytest
from PIL import Image, ImageChops, features

from chrome_lens_py.core import text_renderer
from chrome_lens_py.core.text_renderer import render_translation_overlay
from chrome_lens_py.utils import font_fallback
from chrome_lens_py.utils.lens_betterproto import LensOverlayObjectsResponse

IMG_W, IMG_H = 640, 480

TOP_TO_BOTTOM = 2
RIGHT_TO_LEFT = 1

# --------------------------------------------------------------------- builder


class Box:
    """A line box in pixels: centre, size and clockwise rotation in radians."""

    def __init__(self, cx, cy, w, h, rot=0.0):
        self.cx, self.cy, self.w, self.h, self.rot = cx, cy, w, h, rot


def _set_box(geometry, box: Box, w: int = IMG_W, h: int = IMG_H) -> None:
    target = geometry.bounding_box
    target.center_x = box.cx / w
    target.center_y = box.cy / h
    target.width = box.w / w
    target.height = box.h / h
    target.rotation_z = box.rot


def patch_png(colour=(236, 232, 220), size=(24, 12)) -> bytes:
    """A small, deterministic stand-in for the server's inpainted background."""
    image = Image.new("RGB", size, colour)
    for x in range(size[0]):
        image.putpixel((x, 0), (colour[0] - 20, colour[1] - 20, colour[2] - 20))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def add_paragraph(
    response,
    boxes: Sequence[Box],
    line_texts: Sequence[str],
    *,
    target="ru",
    direction=0,
    alignment=2,
    separator=" ",
    text_color=0xFF202020,
    background_color=0xFFECE8DC,
    patch: Optional[bytes] = None,
    paragraph_box: Optional[Box] = None,
    paddings: Tuple[float, float] = (0.4, 0.4),
):
    """Append one source paragraph and its translation to ``response``."""
    paragraph = response.text.text_layout.paragraphs.add()
    for box in boxes:
        line = paragraph.lines.add()
        _set_box(line.geometry, box)
    if paragraph_box is None:
        left = min(b.cx - b.w / 2 for b in boxes)
        right = max(b.cx + b.w / 2 for b in boxes)
        top = min(b.cy - b.h / 2 for b in boxes)
        bottom = max(b.cy + b.h / 2 for b in boxes)
        paragraph_box = Box(
            (left + right) / 2, (top + bottom) / 2, right - left, bottom - top
        )
    _set_box(paragraph.geometry, paragraph_box)

    gleam = response.deep_gleams.add()
    data = gleam.translation
    data.status.code = 1
    data.target_language = target
    data.source_language = "ja" if direction == TOP_TO_BOTTOM else "en"
    data.translation = separator.join(line_texts)
    data.writing_direction = direction
    data.alignment = alignment

    cursor = 0
    for text in line_texts:
        tline = data.line.add()
        tline.style.text_color = text_color
        tline.style.background_primary_color = background_color
        words = text.split(separator) if separator else [text]
        for word in words:
            entry = tline.word.add()
            entry.start = cursor
            entry.end = cursor + len(word)
            cursor += len(word) + len(separator)
        if patch is not None:
            tline.background_image_data.background_image = patch
            tline.background_image_data.image_width = 24
            tline.background_image_data.image_height = 12
            tline.background_image_data.vertical_padding = paddings[0]
            tline.background_image_data.horizontal_padding = paddings[1]
    return paragraph, data


def source_image() -> Image.Image:
    """A busy but deterministic page: gradient, panels, and 'source text' bars."""
    image = Image.new("RGB", (IMG_W, IMG_H))
    pixels = image.load()
    for y in range(IMG_H):
        for x in range(IMG_W):
            pixels[x, y] = (200 + (x * 40) // IMG_W, 205 + (y * 30) // IMG_H, 190)
    return image


def standard_scene() -> LensOverlayObjectsResponse:
    """Horizontal, rotated, vertical-kept, vertical-reflowed and flat-fill text."""
    response = LensOverlayObjectsResponse()
    patch = patch_png()

    add_paragraph(
        response,
        [Box(160, 60, 220, 30), Box(160, 94, 200, 30)],
        ["Welcome to the old harbour", "Open every day"],
        patch=patch,
    )
    add_paragraph(
        response,
        [Box(470, 70, 240, 28, rot=0.2)],
        ["Fresh bread and coffee"],
        alignment=0,
        patch=patch,
    )
    add_paragraph(
        response,
        [Box(80, 300, 34, 200), Box(40, 300, 34, 180)],
        ["今日はいい天気ですね", "散歩に行こう"],
        target="ja",
        direction=TOP_TO_BOTTOM,
        separator="",
        patch=patch,
        paddings=(0.05, 0.05),
    )
    add_paragraph(
        response,
        [Box(300, 300, 34, 200), Box(260, 300, 34, 180)],
        ["It is such a nice day", "Let us go for a walk"],
        target="en",
        direction=TOP_TO_BOTTOM,
        patch=patch,
        paddings=(0.05, 0.05),
    )
    add_paragraph(
        response,
        [Box(500, 330, 200, 26), Box(500, 362, 160, 26)],
        ["No inpainted patch here", "just a flat fill"],
        alignment=1,
        text_color=0xFF102060,
        background_color=0xFFF4F0E0,
    )
    return response


# ---------------------------------------------------------------- golden hashes


def _digest(image: Image.Image) -> str:
    return hashlib.sha256(
        f"{image.mode}{image.size}".encode() + image.tobytes()
    ).hexdigest()


# Pillow's rasteriser output is only stable for one (Pillow, FreeType) pair, so
# the hashes below are recorded for exactly this pair and the test steps aside
# on any other. Regenerate with:  python tests/test_renderer.py
GOLDEN_ENV = ("12.2.0", "2.14.3")
GOLDEN_VARIANTS = {
    "default": {},
    "hull": {"erase_mode": "hull"},
    "keep_vertical": {"vertical_text": "keep"},
    "align_left": {"text_align": "left"},
    "no_background": {"draw_background": False},
}
GOLDEN = {
    "default": "d3a28291d8b43bb6c3a980a4f2591e4ccf781bf064229ce8e6b416dae2abcf98",
    "hull": "3fb6269031469b142237805083e88d0244fc507b1042ae929b7c0b38d81617cd",
    "keep_vertical": "688bf380093d7564e77e8f21d3646c4088ab58d48f900d5aaec84d275dc13d68",
    "align_left": "73fa46d79d26846e755aad94077fb3f658d7fa0fc34cedc21c51183bdb9dfecf",
    "no_background": "f768bff2e58582321b764e903520d3dbf83fb4654c83718d4be523e5000f5992",
}


def _env() -> Tuple[str, str]:
    import PIL

    return PIL.__version__, features.version("freetype2") or ""


@pytest.fixture
def hermetic_fonts(monkeypatch):
    """Take the machine's installed fonts out of the picture.

    Font selection reads the system font directories, so a pixel hash would
    differ on every machine. With no face resolved, every line is drawn with
    Pillow's bundled default font.
    """
    monkeypatch.setattr(font_fallback, "resolve_font_for_text", lambda *a, **k: None)
    monkeypatch.setattr(
        font_fallback, "resolve_font_face_for_text", lambda *a, **k: None, raising=False
    )
    monkeypatch.setattr(
        font_fallback,
        "split_by_coverage_faces",
        lambda text, *a, **k: [(text, None)] if text else [],
        raising=False,
    )


def render_variant(name: str) -> Image.Image:
    return render_translation_overlay(
        source_image(), standard_scene(), font_path=None, **GOLDEN_VARIANTS[name]
    )


@pytest.mark.parametrize("name", sorted(GOLDEN_VARIANTS))
def test_default_path_is_pixel_identical_to_the_recorded_render(hermetic_fonts, name):
    if _env() != GOLDEN_ENV:
        pytest.skip(f"golden hashes recorded for Pillow/FreeType {GOLDEN_ENV}")
    assert _digest(render_variant(name)) == GOLDEN[name]


# ---------------------------------------------------------------------- helpers

RED, GREEN, BLUE = 0xFFFF0000, (0, 200, 0), 0xFF0000FF


def _pixels(image: Image.Image) -> List[Tuple[int, int, int, int]]:
    raw = image.convert("RGBA").tobytes()
    return list(zip(raw[0::4], raw[1::4], raw[2::4], raw[3::4]))


def _differs(a: Image.Image, b: Image.Image) -> bool:
    """Whether two images differ anywhere. (RGBA getbbox looks at alpha only.)"""
    return (
        ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox() is not None
    )


def _count(image: Image.Image, rgb: Tuple[int, int, int]) -> int:
    """How many pixels are exactly `rgb`, fully opaque."""
    wanted = rgb + (255,)
    return sum(1 for pixel in _pixels(image) if pixel == wanted)


def _ink_bbox(image: Image.Image, rgb=(255, 0, 0)):
    """Bounding box of the pixels that are pure text colour."""
    mask = Image.new("L", image.size, 0)
    wanted = rgb + (255,)
    mask.putdata([255 if p == wanted else 0 for p in _pixels(image)])
    return mask.getbbox()


def _find_font(*names: str) -> Optional[str]:
    for name in names:
        located = font_fallback._locate(name)
        if located:
            return located
    return None


def _latin_font() -> Optional[str]:
    return _find_font(
        "arial.ttf",
        "Arial.ttf",
        "segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    )


def _cjk_font() -> Optional[str]:
    return _find_font(
        "YuGothR.ttc",
        "msyh.ttc",
        "msgothic.ttc",
        "PingFang.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )


def single_paragraph(kind: str, **kw) -> LensOverlayObjectsResponse:
    """One paragraph of the given kind, in loud colours that are easy to count."""
    response = LensOverlayObjectsResponse()
    common = dict(text_color=RED, background_color=BLUE, patch=patch_png(GREEN))
    common.update(kw)
    if kind == "horizontal":
        add_paragraph(
            response, [Box(320, 240, 300, 40)], ["Hello wide world"], **common
        )
    elif kind == "vertical":
        add_paragraph(
            response,
            [Box(320, 240, 40, 220)],
            ["今日はいい天気ですね"],
            target="ja",
            direction=TOP_TO_BOTTOM,
            separator="",
            **{"paddings": (0.05, 0.05), **common},
        )
    elif kind == "reflow":
        add_paragraph(
            response,
            [Box(360, 240, 40, 220), Box(310, 240, 40, 200)],
            ["Such a lovely day", "let us walk"],
            target="en",
            direction=TOP_TO_BOTTOM,
            **{"paddings": (0.05, 0.05), **common},
        )
    return response


def render(kind: str, font_path=None, scene_kw=None, **kw) -> Image.Image:
    return render_translation_overlay(
        source_image(), single_paragraph(kind, **(scene_kw or {})), font_path, **kw
    )


# --------------------------------------------------------------------- outline


@pytest.mark.parametrize(
    "size,scale,expected",
    [
        (40, 1.0, 1),
        (100, 1.0, 2),
        (100, 2.0, 4),
        (3, 1.0, 1),
        (100, 0, 0),
        (100, -1, 0),
    ],
)
def test_outline_px(size, scale, expected):
    from chrome_lens_py.core.render_common import outline_px

    assert outline_px(size, scale) == expected


@pytest.mark.parametrize("kind", ["horizontal", "vertical", "reflow"])
def test_outline_scale_zero_removes_the_outline_in_every_branch(hermetic_fonts, kind):
    # The outline is drawn in the line's background colour (blue here) and the
    # patch is green, so any pure blue pixel is outline.
    with_outline = _count(render(kind), (0, 0, 255))
    without = _count(render(kind, outline_scale=0), (0, 0, 255))
    assert with_outline > 0
    assert without == 0


@pytest.mark.parametrize("kind", ["vertical", "reflow"])
def test_outline_scale_scales_the_outline_in_vertical_and_reflow(hermetic_fonts, kind):
    base = _count(render(kind), (0, 0, 255))
    thick = _count(render(kind, outline_scale=12), (0, 0, 255))
    assert thick > base


# ----------------------------------------------------------- readable-size floor


def test_floor_enlarges_vertical_text_and_does_not_clip_it(hermetic_fonts):
    plain = _ink_bbox(render("vertical"))
    floored = _ink_bbox(render("vertical", min_readable_px=30))
    assert plain and floored
    plain_h = plain[3] - plain[1]
    floored_h = floored[3] - floored[1]
    assert floored_h > plain_h * 1.5
    # More text than the 220px column holds: it is drawn, not cut to the box.
    assert floored_h > 220


def test_floored_horizontal_text_is_not_clipped_to_its_box(hermetic_fonts):
    floored = _ink_bbox(render("horizontal", min_readable_px=48))
    # The line box is 300px wide; at 48px the text is wider and must be whole.
    assert floored[2] - floored[0] > 300


@pytest.mark.parametrize(
    "kind,mode",
    [
        ("horizontal", {}),
        ("vertical", {}),
        ("horizontal", {"erase_mode": "hull"}),
        ("vertical", {"erase_mode": "hull", "vertical_text": "keep"}),
        ("reflow", {"erase_mode": "hull"}),
        ("reflow", {}),
    ],
)
def test_floor_never_grows_the_erased_area(hermetic_fonts, kind, mode):
    # With the text itself invisible and no outline, what is left on the canvas
    # is exactly the erased area. It is a function of the detected boxes alone,
    # so no readable-size floor may change it - sizing it from the drawn text is
    # what once painted black bars across a manga page.
    kw = dict(scene_kw={"text_color": 0x00FF0000}, outline_scale=0, **mode)
    low = render(kind, **kw)
    high = render(kind, min_readable_px=60, **kw)
    assert not _differs(low, high)
    assert _differs(low, source_image())


def test_vertical_tile_is_sized_from_the_measured_text_not_a_ratio():
    from chrome_lens_py.core.render_fonts import FontPlan
    from chrome_lens_py.core.render_vertical import (
        measure_vertical,
        render_vertical_tile,
    )

    plan = FontPlan.fixed(None)
    text = "今日はいい天気ですね"
    box_w, box_h = 27, 264
    for size in (3, 24, 60):
        font = plan.at(size)
        col_w, total_h = measure_vertical(text, font)
        tile = render_vertical_tile(
            text,
            font,
            box_w,
            box_h,
            (1, 2, 3, 255),
            1,
            (4, 5, 6, 255),
            "center",
            grow=True,
        )
        assert tile.width <= max(box_w, math.ceil(col_w) + 4)
        assert tile.height <= max(box_h, math.ceil(total_h) + 4)


def test_text_that_fits_gets_a_box_sized_tile():
    from chrome_lens_py.core.render_fonts import FontPlan
    from chrome_lens_py.core.render_vertical import render_vertical_tile

    font = FontPlan.fixed(None).at(8)
    tile = render_vertical_tile(
        "今日", font, 30, 100, (1, 2, 3, 255), 1, None, "center"
    )
    assert tile.size == (30, 100)


# ------------------------------------------------------------------- hull + reflow


def test_hull_with_reflow_does_not_paint_the_patches_back(hermetic_fonts):
    patch = (255, 0, 255)
    scene_kw = {"patch": patch_png(patch, (24, 12)), "background_color": 0xFFF0F0F0}
    hull = render("reflow", scene_kw=scene_kw, erase_mode="hull")
    patched = render("reflow", scene_kw=scene_kw)
    assert _count(patched, patch) > 0
    # Not one pixel of the server's patch survives on top of the hull fill.
    assert _count(hull, patch) == 0


def test_manga_mode_paints_no_patches(hermetic_fonts):
    patch = (255, 0, 255)
    out = render("reflow", scene_kw={"patch": patch_png(patch)}, manga_mode=True)
    assert _count(out, patch) == 0


# ----------------------------------------------------------------------- fonts


def test_fonts_are_opened_once_per_file_face_and_size(monkeypatch):
    from chrome_lens_py.core import render_fonts

    latin = _latin_font()
    if not latin:
        pytest.skip("no TrueType font installed")
    opened: List[tuple] = []
    real = render_fonts.ImageFont.truetype

    def counting(path, size, index=0, **kw):
        opened.append((path, size, index))
        return real(path, size, index=index, **kw)

    monkeypatch.setattr(render_fonts.ImageFont, "truetype", counting)
    render_fonts._load_cached.cache_clear()

    text_renderer.fit_font_size("some text", latin, 300, 40)
    first = len(opened)
    assert 0 < first <= 9  # one binary search: at most log2(147)+1 sizes
    text_renderer.fit_font_size("some text", latin, 300, 40)
    text_renderer.fit_font_size("another line", latin, 300, 40)
    assert len(opened) < first + 9  # the sizes already opened are reused
    assert len(set(opened)) == len(opened)


def test_font_face_index_is_used_for_collections():
    from chrome_lens_py.core.render_fonts import load_font

    path = _find_font("msyh.ttc", "YuGothR.ttc", "PingFang.ttc")
    if not path:
        pytest.skip("no font collection installed")
    count = font_fallback._face_count(path)
    if count < 2:
        pytest.skip("collection has a single face")
    names = {
        load_font(font_fallback.FontFace(path, i), 20).getname() for i in range(count)
    }
    assert len(names) > 1  # face 1 is not silently face 0


def test_resolved_plan_keeps_the_regional_face_index():
    from chrome_lens_py.core.render_fonts import FontPlan

    path = _find_font("msyh.ttc", "YuGothR.ttc", "msgothic.ttc", "PingFang.ttc")
    if not path:
        pytest.skip("no CJK font collection installed")
    plan = FontPlan.resolve("今日", path)
    expected = font_fallback.resolve_font_face_for_text("今日", path)
    # The index the resolver chose is the one the font is opened with.
    assert plan.primary == expected
    assert isinstance(plan.primary.index, int)


def test_resolved_plan_for_cjk_text_uses_a_font_that_has_the_glyphs():
    from chrome_lens_py.core.render_fonts import FontPlan

    latin, cjk = _latin_font(), _cjk_font()
    if not (latin and cjk) or not font_fallback.FONTTOOLS_AVAILABLE:
        pytest.skip("need a Latin font, a CJK font and fontTools")
    if font_fallback.font_supports_text(latin, "世界"):
        pytest.skip("the Latin font covers CJK on this machine")
    plan = FontPlan.resolve("Hello 世界", latin)
    for char in "H世界":
        assert font_fallback.face_has_glyph(plan.face_for(char), char), char


def test_mixed_plan_draws_each_run_in_its_own_face():
    from PIL import ImageDraw

    from chrome_lens_py.core.render_fonts import FontPlan

    latin, cjk = _latin_font(), _cjk_font()
    if not (latin and cjk) or latin == cjk:
        pytest.skip("need a Latin font and a different CJK font")
    latin_face = font_fallback.FontFace(latin, 0)
    cjk_face = font_fallback.resolve_font_face_for_text("世界", cjk)
    plan = FontPlan([("Hello ", latin_face), ("世界", cjk_face)], fallback=latin_face)
    assert plan.mixed
    assert plan.face_for("H") == latin_face and plan.face_for("世") == cjk_face
    assert plan.runs_of("Hello 世界") == [("Hello ", latin_face), ("世界", cjk_face)]

    sized = plan.at(30)
    text = "Hello 世界"
    expected = sum(sized.font(f).getlength(t) for t, f in plan.runs_of(text))
    assert sized.getlength(text) == expected

    tofu = Image.new("RGBA", (260, 60), (255, 255, 255, 255))
    ImageDraw.Draw(tofu).text((5, 5), text, font=sized.font(latin_face), fill="black")
    mixed = Image.new("RGBA", (260, 60), (255, 255, 255, 255))
    sized.draw(ImageDraw.Draw(mixed), (5, 5), text, (0, 0, 0, 255))
    assert _differs(tofu, mixed)  # the CJK run is not the Latin font's tofu


def test_renderer_draws_mixed_scripts_end_to_end():
    latin, cjk = _latin_font(), _cjk_font()
    if not (latin and cjk) or font_fallback.font_supports_text(latin, "世界"):
        pytest.skip("need a Latin-only font and a CJK font")
    response = LensOverlayObjectsResponse()
    add_paragraph(
        response,
        [Box(320, 240, 400, 60)],
        ["Hello 世界"],
        text_color=RED,
        patch=None,
        background_color=0xFFFFFFFF,
    )
    out = render_translation_overlay(source_image(), response, latin)
    box = _ink_bbox(out)
    assert box
    # Chinese glyphs have many strokes; a .notdef box is a plain rectangle, so
    # the right-hand half of the line carries far more ink than two empty boxes.
    left, top, right, bottom = box
    right_half = out.crop(((left + right) // 2, top, right, bottom))
    assert _count(right_half, (255, 0, 0)) > 80


# ---------------------------------------------------------- vertical punctuation


def test_vertical_set_dashes_and_brackets_are_upright_cells():
    for char in "ー—―…‥「」（）【】":
        assert text_renderer._is_upright(char), char
    for char in "A-(":
        assert not text_renderer._is_upright(char), char


def test_glyph_for_rotates_marks_the_font_has_no_vertical_form_for():
    from chrome_lens_py.core.render_fonts import FontPlan
    from chrome_lens_py.core.render_vertical import glyph_for

    plan = FontPlan.fixed(None)  # the default font has no U+FE.. forms
    for char in "ー「」（）―…〜":
        glyph, _, rotate = glyph_for(char, plan)
        assert glyph == char and rotate, char
    for char in "今はA、":
        assert glyph_for(char, plan)[2] is False


def test_glyph_for_prefers_a_vertical_presentation_form_when_the_font_has_it():
    from chrome_lens_py.core.render_fonts import FontPlan
    from chrome_lens_py.core.render_vertical import glyph_for

    path = _find_font("YuGothR.ttc", "msyh.ttc", "PingFang.ttc")
    if not path or not font_fallback.FONTTOOLS_AVAILABLE:
        pytest.skip("no font with vertical forms (or no fontTools)")
    face = font_fallback.FontFace(path, 0)
    if not font_fallback.face_has_glyph(face, "﹁"):
        pytest.skip("font lacks U+FE41")
    plan = FontPlan.fixed(face)
    assert glyph_for("「", plan) == ("﹁", face, False)
    assert glyph_for("」", plan)[0] == "﹂"
    # The long vowel mark has no presentation form: it is turned instead.
    assert glyph_for("ー", plan) == ("ー", face, True)


def test_long_vowel_mark_stands_upright_in_a_vertical_column():
    from chrome_lens_py.core.render_fonts import FontPlan
    from chrome_lens_py.core.render_vertical import render_vertical_tile

    path = _find_font("YuGothR.ttc", "msyh.ttc", "msgothic.ttc", "PingFang.ttc")
    if not path:
        pytest.skip("no CJK font installed")
    font = FontPlan.fixed(path).at(40)
    tile = render_vertical_tile(
        "ー", font, 60, 60, (0, 0, 0, 255), 0, None, "center", grow=False
    )
    left, top, right, bottom = tile.getchannel("A").getbbox()
    # Horizontal it would be a wide bar; a quarter turn makes it a tall one.
    assert (bottom - top) > (right - left)


def test_vertical_cjk_dash_uses_the_same_cell_height_as_a_kanji():
    from chrome_lens_py.core.render_fonts import FontPlan
    from chrome_lens_py.core.render_vertical import measure_vertical

    font = FontPlan.fixed(None).at(20)
    _, kanji = measure_vertical("今", font)
    _, dash = measure_vertical("―", font)
    assert dash == kanji


# --------------------------------------------------------------------- misc


def test_composite_clips_instead_of_failing_at_the_edges():
    from chrome_lens_py.core.render_common import composite

    canvas = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
    tile = Image.new("RGBA", (6, 6), (255, 0, 0, 255))
    composite(canvas, tile, -3, -2)
    composite(canvas, tile, 8, 8)
    composite(canvas, tile, 50, 50)
    composite(canvas, tile, -50, 0)
    assert canvas.getpixel((0, 0)) == (255, 0, 0, 255)
    assert canvas.getpixel((2, 3)) == (255, 0, 0, 255)
    assert canvas.getpixel((3, 4)) == (0, 0, 0, 255)
    assert canvas.getpixel((9, 9)) == (255, 0, 0, 255)


def test_rtl_paragraph_renders_without_raqm(hermetic_fonts):
    response = LensOverlayObjectsResponse()
    add_paragraph(
        response,
        [Box(320, 240, 300, 40)],
        ["مرحبا بالعالم"],
        target="ar",
        text_color=RED,
        patch=None,
        background_color=0xFFFFFFFF,
    )
    out = render_translation_overlay(source_image(), response, None)
    assert out.size == (IMG_W, IMG_H)


def test_u16_slice_cache_does_not_change_results():
    text = "a😀bc"
    for _ in range(3):
        assert text_renderer._u16_slice(text, 1, 3) == "😀"
        assert text_renderer._u16_slice(text, 3, 5) == "bc"


if __name__ == "__main__":  # pragma: no cover - regenerates the table above
    import unittest.mock as mock

    with (
        mock.patch.object(font_fallback, "resolve_font_for_text", lambda *a, **k: None),
        mock.patch.object(
            font_fallback,
            "resolve_font_face_for_text",
            lambda *a, **k: None,
            create=True,
        ),
        mock.patch.object(
            font_fallback,
            "split_by_coverage_faces",
            lambda text, *a, **k: [(text, None)] if text else [],
            create=True,
        ),
    ):
        print("GOLDEN_ENV =", _env())
        for variant in GOLDEN_VARIANTS:
            print(f'    "{variant}": "{_digest(render_variant(variant))}",')
    sys.exit(0)
