"""Serialisers for OCR results: json, jsonl, hOCR and tesseract-style TSV.

Everything here is a pure function over the dict that
``LensAPI.process_image(..., output_format="detailed")`` returns, wrapped in a
:class:`Page` together with the file name and the pixel size of the image. The
size is not part of that dict (Lens reports geometry normalised to 0..1), so the
caller has to supply it; formats that need pixels refuse to guess.

Shape of the input, as far as this module relies on it::

    result["detailed_blocks"] = [          # paragraphs
        {"text": str, "geometry": G,
         "lines": [{"text": str, "geometry": G,
                    "words": [{"text": str, "separator": str,
                               "geometry": G | None}]}]}]
    result["translated_text"], result["detected_language"]

where ``G`` is ``{"center_x", "center_y", "width", "height", "angle_deg"}``
normalised to the image (or in pixels when it says ``"coordinate_type":
"IMAGE"``).
"""

import json
import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

FORMATS = ("text", "json", "jsonl", "hocr", "tsv")

Box = Tuple[int, int, int, int]  # left, top, right, bottom in pixels


@dataclass
class Page:
    """One processed image."""

    file: str
    result: Dict[str, Any]
    width: Optional[int] = None
    height: Optional[int] = None


# ------------------------------------------------------------------ geometry


def pixel_box(
    geometry: Optional[Dict[str, Any]], width: int, height: int
) -> Optional[Box]:
    """Axis-aligned pixel box enclosing a (possibly rotated) Lens box."""
    if not geometry:
        return None
    if geometry.get("coordinate_type") == "IMAGE":
        sx = sy = 1.0
    else:
        sx, sy = float(width), float(height)

    cx, cy = geometry["center_x"] * sx, geometry["center_y"] * sy
    half_w, half_h = geometry["width"] * sx / 2, geometry["height"] * sy / 2
    angle = math.radians(geometry.get("angle_deg") or 0.0)
    cos, sin = abs(math.cos(angle)), abs(math.sin(angle))
    ext_x = cos * half_w + sin * half_h
    ext_y = sin * half_w + cos * half_h

    left = max(0, int(math.floor(cx - ext_x)))
    top = max(0, int(math.floor(cy - ext_y)))
    right = min(width, int(math.ceil(cx + ext_x)))
    bottom = min(height, int(math.ceil(cy + ext_y)))
    return left, top, max(left, right), max(top, bottom)


def _union(boxes: Iterable[Optional[Box]]) -> Optional[Box]:
    real = [b for b in boxes if b]
    if not real:
        return None
    return (
        min(b[0] for b in real),
        min(b[1] for b in real),
        max(b[2] for b in real),
        max(b[3] for b in real),
    )


def _require_size(page: Page) -> Tuple[int, int]:
    if not page.width or not page.height:
        raise ValueError(
            f"The pixel size of '{page.file}' is unknown, which this format needs."
        )
    return page.width, page.height


def _blocks(page: Page) -> List[Dict[str, Any]]:
    return page.result.get("detailed_blocks") or []


# ---------------------------------------------------------------- plain text


def ocr_text(result: Dict[str, Any], preserve_line_breaks: bool = True) -> str:
    """The recognised text, for either a full_text or a detailed result."""
    if "ocr_text" in result:
        return result["ocr_text"] or ""
    text = "\n".join(
        "\n".join(line.get("text", "") for line in block.get("lines", []))
        for block in result.get("detailed_blocks") or []
    )
    return text if preserve_line_breaks else " ".join(text.split())


# ---------------------------------------------------------------------- json


def _box_dict(box: Optional[Box]) -> Optional[Dict[str, int]]:
    if not box:
        return None
    return {
        "left": box[0],
        "top": box[1],
        "width": box[2] - box[0],
        "height": box[3] - box[1],
    }


def _node(item: Dict[str, Any], page: Page, with_pixels: bool) -> Dict[str, Any]:
    node: Dict[str, Any] = {"text": item.get("text", "")}
    if "separator" in item:
        node["separator"] = item["separator"]
    for key in ("type", "latex"):
        if key in item:
            node[key] = item[key]
    node["geometry"] = item.get("geometry")
    if with_pixels:
        node["bbox"] = _box_dict(pixel_box(item.get("geometry"), page.width, page.height))  # type: ignore[arg-type]
    return node


def page_to_dict(page: Page, preserve_line_breaks: bool = True) -> Dict[str, Any]:
    """JSON-safe description of one page. Pixel boxes appear when the size is known."""
    with_pixels = bool(page.width and page.height)
    blocks = []
    for block in _blocks(page):
        out = _node(block, page, with_pixels)
        out["lines"] = []
        for line in block.get("lines", []):
            line_out = _node(line, page, with_pixels)
            line_out["words"] = [
                _node(word, page, with_pixels) for word in line.get("words", [])
            ]
            out["lines"].append(line_out)
        blocks.append(out)

    return {
        "file": page.file,
        "width": page.width,
        "height": page.height,
        "detected_language": page.result.get("detected_language"),
        "ocr_text": ocr_text(page.result, preserve_line_breaks),
        "translated_text": page.result.get("translated_text"),
        "blocks": blocks,
    }


def error_record(file: str, error: str) -> Dict[str, Any]:
    return {"file": file, "error": error}


def format_json(records: Sequence[Dict[str, Any]], indent: Optional[int] = 2) -> str:
    """One object for one image, an array for several. Always a single document."""
    payload: Any = records[0] if len(records) == 1 else list(records)
    return json.dumps(payload, indent=indent, ensure_ascii=False)


def format_jsonl_line(record: Dict[str, Any]) -> str:
    """One compact JSON object on one line (no embedded newlines)."""
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def oneline_record(
    file: str,
    ocr_text: Optional[str] = None,
    translated_text: Optional[str] = None,
    error: Optional[str] = None,
) -> str:
    """The ``--oneline`` line: {"file", "ocr_text", "translated_text", "error"}."""
    return format_jsonl_line(
        {
            "file": file,
            "ocr_text": ocr_text,
            "translated_text": translated_text,
            "error": error,
        }
    )


# ---------------------------------------------------------------------- hocr

_HOCR_HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}" lang="{lang}">
<head>
<title></title>
<meta http-equiv="Content-Type" content="text/html;charset=utf-8" />
<meta name="ocr-system" content="chrome-lens-py" />
<meta name="ocr-capabilities" content="ocr_page ocr_carea ocr_par ocr_line ocrx_word" />
</head>
<body>
"""


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;", "'": "&#39;"})


def _bbox(box: Optional[Box], fallback: Box) -> str:
    left, top, right, bottom = box or fallback
    return f"bbox {left} {top} {right} {bottom}"


def _line_words(line: Dict[str, Any], width: int, height: int):
    """(text, box) for every non-empty word, falling back to the line's box."""
    line_box = pixel_box(line.get("geometry"), width, height)
    for word in line.get("words", []):
        text = word.get("text", "")
        if not text.strip():
            continue
        yield text, pixel_box(word.get("geometry"), width, height) or line_box


def format_hocr(pages: Sequence[Page]) -> str:
    """hOCR 1.2 (valid XHTML): ocr_page > ocr_carea > ocr_par > ocr_line > ocrx_word."""
    languages = [p.result.get("detected_language") for p in pages]
    lang = next((lang for lang in languages if lang), "en")
    out = [_HOCR_HEAD.format(lang=_attr(lang))]

    for page_no, page in enumerate(pages, start=1):
        width, height = _require_size(page)
        page_box: Box = (0, 0, width, height)
        out.append(
            f'<div class="ocr_page" id="page_{page_no}" '
            f'title="image &quot;{_attr(page.file)}&quot;; '
            f'{_bbox(None, page_box)}; ppageno {page_no - 1}">\n'
        )
        for b, block in enumerate(_blocks(page), start=1):
            block_box = pixel_box(block.get("geometry"), width, height)
            out.append(
                f'<div class="ocr_carea" id="block_{page_no}_{b}" '
                f'title="{_bbox(block_box, page_box)}">\n'
                f'<p class="ocr_par" id="par_{page_no}_{b}" '
                f'title="{_bbox(block_box, page_box)}">\n'
            )
            for ln, line in enumerate(block.get("lines", []), start=1):
                words = list(_line_words(line, width, height))
                line_box = pixel_box(line.get("geometry"), width, height) or _union(
                    box for _, box in words
                )
                out.append(
                    f'<span class="ocr_line" id="line_{page_no}_{b}_{ln}" '
                    f'title="{_bbox(line_box, block_box or page_box)}">'
                )
                spans = []
                for w, (text, box) in enumerate(words, start=1):
                    spans.append(
                        f'<span class="ocrx_word" id="word_{page_no}_{b}_{ln}_{w}" '
                        f'title="{_bbox(box, line_box or page_box)}">'
                        f"{escape(text)}</span>"
                    )
                out.append(" ".join(spans) + "</span>\n")
            out.append("</p>\n</div>\n")
        out.append("</div>\n")

    out.append("</body>\n</html>\n")
    return "".join(out)


# ----------------------------------------------------------------------- tsv

TSV_COLUMNS = (
    "level",
    "page_num",
    "block_num",
    "par_num",
    "line_num",
    "word_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
)


def _tsv_text(text: str) -> str:
    return " ".join(text.split())


def format_tsv(pages: Sequence[Page]) -> str:
    """Tesseract-compatible TSV (levels 1 page, 2 block, 3 paragraph, 4 line, 5 word).

    Lens reports no confidence. Words get 100 and structural rows -1, which is
    what tesseract uses for them, so consumers that filter on ``conf >= 0``
    keep the words.
    """
    rows: List[Tuple[Any, ...]] = [TSV_COLUMNS]

    def row(level, page_no, b, p, ln, w, box: Box, conf, text=""):
        rows.append(
            (
                level,
                page_no,
                b,
                p,
                ln,
                w,
                box[0],
                box[1],
                box[2] - box[0],
                box[3] - box[1],
                conf,
                text,
            )
        )

    for page_no, page in enumerate(pages, start=1):
        width, height = _require_size(page)
        page_box: Box = (0, 0, width, height)
        row(1, page_no, 0, 0, 0, 0, page_box, -1)
        for b, block in enumerate(_blocks(page), start=1):
            block_box = pixel_box(block.get("geometry"), width, height) or page_box
            row(2, page_no, b, 0, 0, 0, block_box, -1)
            row(3, page_no, b, 1, 0, 0, block_box, -1)
            for ln, line in enumerate(block.get("lines", []), start=1):
                words = list(_line_words(line, width, height))
                line_box = (
                    pixel_box(line.get("geometry"), width, height)
                    or _union(box for _, box in words)
                    or block_box
                )
                row(4, page_no, b, 1, ln, 0, line_box, -1)
                for w, (text, box) in enumerate(words, start=1):
                    row(5, page_no, b, 1, ln, w, box or line_box, 100, _tsv_text(text))

    return "\n".join("\t".join(str(c) for c in r) for r in rows) + "\n"
