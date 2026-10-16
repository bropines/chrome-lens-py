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
    "hull": "b9d35ad42a2e968308f733e97ff64c280b480837094fad2521e30d5158158faf",
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
