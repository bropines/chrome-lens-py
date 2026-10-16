"""Fonts for the overlay renderer: a shared cache, face-aware fallback, measuring.

Three things live here because the renderer needs them everywhere at once.

``load_font`` is the only place ``ImageFont.truetype`` is called. The renderer
asks for the same (file, face, size) many times - every step of every binary
search, once per line - and opening a font is by far the dearest thing it does,
so the result is cached.

``FontPlan`` answers "which face draws which character" for one piece of text.
A single font file rarely covers a line that mixes scripts, and a .ttc holds
several regional designs that differ only by face index, so both the file and the
index matter. Most lines resolve to one face; those take a fast path with no
per-character work at all.

``SizedPlan`` is a plan at one pixel size and quacks like a Pillow font for the
two calls the layout code makes (``getlength`` and ``getmetrics``), plus a
``draw`` that handles drawing a line in several faces on a common baseline.
"""

import logging
import threading
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple, Union

from PIL import ImageDraw, ImageFont

from ..constants import RENDER_MAX_FONT_SIZE, RENDER_MIN_FONT_SIZE
from ..utils.font_fallback import FontFace

logger = logging.getLogger(__name__)

Face = Optional[FontFace]  # None means Pillow's bundled default font.

__all__ = [
    "Face",
    "FontPlan",
    "SizedPlan",
    "clamp_size",
    "load_font",
]


def clamp_size(size: float) -> int:
    return max(RENDER_MIN_FONT_SIZE, min(int(size), RENDER_MAX_FONT_SIZE))


@lru_cache(maxsize=1024)
def _load_cached(
    path: Optional[str], index: int, size: int, thread: int
) -> ImageFont.FreeTypeFont:
    # `thread` is part of the key on purpose: a FreeType face is not safe to use
    # from two threads at once, and the API may render from an executor. Each
    # thread therefore gets its own handles; the cache stays bounded by maxsize.
    if path:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError as e:
            logger.warning(
                "Cannot open font '%s' (face %d): %s. Using the default font.",
                path,
                index,
                e,
            )
    return ImageFont.load_default(size)


def load_font(face: Face, size: float) -> ImageFont.FreeTypeFont:
    """The font for `face` at `size` px, clamped to the renderer's range."""
    path, index = (face.path, face.index) if face is not None else (None, 0)
    return _load_cached(path, index, clamp_size(size), threading.get_ident())


class FontPlan:
    """Which face draws each character of one piece of text.

    Build it with :meth:`resolve` to get per-script fallback, or :meth:`fixed`
    to pin one face. ``plan.at(size)`` yields a :class:`SizedPlan`.
    """

    def __init__(
        self,
        runs: Sequence[Tuple[str, Face]],
        fallback: Face = None,
    ):
        self._fallback = fallback
        resolved = [(chunk, face or fallback) for chunk, face in runs]
        faces: List[Face] = []
        for _, face in resolved:
            if face not in faces:
                faces.append(face)
        if not faces:
            faces.append(fallback)
        self.faces: Tuple[Face, ...] = tuple(faces)
        self.primary: Face = self.faces[0]

        # Only a mixed plan needs a character table. A character that ended up
        # in two different faces (spaces and punctuation follow whichever run
        # they sit in) is ambiguous and is left out: it joins its neighbour.
        self._by_char: Dict[str, Face] = {}
        if len(self.faces) > 1:
            ambiguous = set()
            for chunk, face in resolved:
                for char in chunk:
                    if self._by_char.setdefault(char, face) != face:
                        ambiguous.add(char)
            for char in ambiguous:
                del self._by_char[char]
        self._sized: Dict[int, "SizedPlan"] = {}

    @classmethod
    def fixed(cls, font: Union[str, FontFace, None]) -> "FontPlan":
        """A plan that always uses one face: a path, a FontFace, or None."""
        if isinstance(font, FontFace):
            face: Face = font
        elif font:
            face = FontFace(str(font), 0)
        else:
            face = None
        return cls([], fallback=face)

    @classmethod
    def resolve(cls, text: str, preferred_path: Optional[str]) -> "FontPlan":
        """Pick faces for `text`, keeping `preferred_path` wherever it works.

        Never raises: font selection failing must not fail a render, so any
        trouble degrades to the preferred file (or the default font).
        """
        fallback: Face = FontFace(preferred_path, 0) if preferred_path else None
        try:
            from ..utils.font_fallback import split_by_coverage_faces

            runs = split_by_coverage_faces(text, preferred_path)
        except Exception as e:  # pragma: no cover - resolver is best effort
            logger.debug("Font fallback failed, using the configured font: %s", e)
            return cls([], fallback=fallback)
        return cls(runs, fallback=fallback)

    @property
    def mixed(self) -> bool:
        return len(self.faces) > 1

    def face_for(self, char: str) -> Face:
        """The face a character is drawn with (the primary one when unsure)."""
        return self._by_char.get(char, self.primary)

    def runs_of(self, text: str) -> List[Tuple[str, Face]]:
        """Split a substring into (chunk, face) runs, merging equal neighbours."""
        if not self.mixed:
            return [(text, self.primary)] if text else []
        runs: List[Tuple[str, Face]] = []
        previous = self.primary
        for char in text:
            face = self._by_char.get(char, previous)
            if runs and runs[-1][1] == face:
                runs[-1] = (runs[-1][0] + char, face)
            else:
                runs.append((char, face))
            previous = face
        return runs

    def at(self, size: float) -> "SizedPlan":
        key = clamp_size(size)
        sized = self._sized.get(key)
        if sized is None:
            sized = self._sized[key] = SizedPlan(self, key)
        return sized


class SizedPlan:
    """A :class:`FontPlan` at one size, usable where layout code wants a font."""

    def __init__(self, plan: FontPlan, size: int):
        self.plan = plan
        self.size = size
        self._primary = load_font(plan.primary, size)
        self._metrics: Optional[Tuple[int, int]] = None
        self._lengths: Dict[str, float] = {}

    def font(self, face: Face) -> ImageFont.FreeTypeFont:
        return load_font(face, self.size)

    def getmetrics(self) -> Tuple[int, int]:
        """(ascent, descent) of the tallest face in the plan.

        Taking the maximum keeps line height the same whichever faces a given
        line happens to use, so a column of text does not jitter.
        """
        if self._metrics is None:
            if not self.plan.mixed:
                self._metrics = self._primary.getmetrics()
            else:
                pairs = [self.font(face).getmetrics() for face in self.plan.faces]
                self._metrics = (
                    max(p[0] for p in pairs),
                    max(p[1] for p in pairs),
                )
        return self._metrics

    def getlength(self, text: str) -> float:
        if not self.plan.mixed:
            return self._primary.getlength(text)
        cached = self._lengths.get(text)
        if cached is None:
            cached = self._lengths[text] = sum(
                self.font(face).getlength(chunk)
                for chunk, face in self.plan.runs_of(text)
            )
        return cached

    def draw(
        self,
        draw: ImageDraw.ImageDraw,
        xy: Tuple[float, float],
        text: str,
        fill,
        stroke_width: int = 0,
        stroke_fill=None,
        face: Face = None,
    ) -> None:
        """Draw `text` with its top-left at `xy`, switching faces per run.

        `face` forces one face for the whole string (used for glyphs that are
        not in the original text, such as vertical presentation forms).
        """
        if not self.plan.mixed:
            draw.text(
                xy,
                text,
                font=self._primary,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
            return

        # Faces have different ascents, so runs are aligned on the baseline of
        # the tallest one rather than on their own tops.
        x, y = xy
        baseline = y + self.getmetrics()[0]
        runs = [(text, face)] if face is not None else self.plan.runs_of(text)
        for chunk, run_face in runs:
            font = self.font(run_face)
            draw.text(
                (x, baseline),
                chunk,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
                anchor="ls",
            )
            x += font.getlength(chunk)
