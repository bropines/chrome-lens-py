"""Small drawing helpers shared by the overlay renderer modules."""

from PIL import Image

from ..constants import RENDER_OUTLINE_RATIO


def outline_px(font_size: float, scale: float = 1.0) -> int:
    """Outline thickness for a font size, 0 when the outline is switched off.

    Chromium draws the outline at fontSize * 0.02, never thinner than a pixel;
    `scale` multiplies that, and a scale of zero or less removes it entirely.
    """
    if scale <= 0:
        return 0
    return max(1, round(font_size * RENDER_OUTLINE_RATIO * scale))


def composite(dest: Image.Image, src: Image.Image, x: float, y: float) -> None:
    """alpha_composite that tolerates `src` hanging off the edge of `dest`.

    Whatever falls outside is clipped, so callers can place a rotated or
    enlarged tile without first working out whether it still fits.
    """
    x, y = int(x), int(y)
    left, top = max(0, -x), max(0, -y)
    right = min(src.width, dest.width - x)
    bottom = min(src.height, dest.height - y)
    if right <= left or bottom <= top:
        return
    if (left, top, right, bottom) != (0, 0, src.width, src.height):
        src = src.crop((left, top, right, bottom))
    dest.alpha_composite(src, (x + left, y + top))
