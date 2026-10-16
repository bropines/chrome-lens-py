"""Offline tests for chrome_lens_py.formats, on a synthetic detailed result."""

import csv
import io
import json
import xml.etree.ElementTree as ET

import pytest

from chrome_lens_py import formats
from chrome_lens_py.formats import Page

XHTML = "{http://www.w3.org/1999/xhtml}"


def geo(cx, cy, w, h, angle=0.0):
    return {
        "center_x": cx,
        "center_y": cy,
        "width": w,
        "height": h,
        "angle_deg": angle,
        "coordinate_type": "NORMALIZED",
    }


def word(text, cx, cy, w, h, separator=" "):
    return {"text": text, "separator": separator, "geometry": geo(cx, cy, w, h)}


def make_result():
    """Two lines in one paragraph on a 200x100 image."""
    return {
        "translated_text": "Привет",
        "detected_language": "en",
        "word_data": [],
        "objects": [],
        "translation_render_data": [],
        "detailed_blocks": [
            {
                "text": "Hello <b> & co\nsecond",
                "geometry": geo(0.5, 0.5, 0.8, 0.6),
                "lines": [
                    {
                        "text": "Hello <b> & co",
                        "geometry": geo(0.5, 0.3, 0.8, 0.2),
                        "words": [
                            word("Hello", 0.25, 0.25, 0.3, 0.2),
                            word("<b>", 0.5, 0.25, 0.2, 0.2),
                            word("&", 0.7, 0.25, 0.1, 0.2),
                            # no geometry: falls back to the line's box
                            {"text": "co", "separator": "", "geometry": None},
                        ],
                    },
                    {
                        "text": "second",
                        "geometry": geo(0.5, 0.6, 0.4, 0.2),
                        "words": [word("second", 0.5, 0.6, 0.4, 0.2, "")],
                    },
                ],
            }
        ],
    }


@pytest.fixture
def page():
    return Page(file='dir/we"ird.png', result=make_result(), width=200, height=100)


# ------------------------------------------------------------------ geometry


def test_pixel_box_scales_normalized_geometry():
    assert formats.pixel_box(geo(0.25, 0.25, 0.3, 0.2), 200, 100) == (20, 15, 80, 35)


def test_pixel_box_encloses_rotated_box():
    # 90 degrees swaps the extents: 60x20 px becomes 20x60 px around the centre.
    left, top, right, bottom = formats.pixel_box(geo(0.5, 0.5, 0.3, 0.2, 90), 200, 100)
    assert (right - left, bottom - top) == (20, 60)


def test_pixel_box_clamps_to_image_and_handles_missing():
    assert formats.pixel_box(geo(0.0, 0.0, 1.0, 1.0), 100, 50) == (0, 0, 50, 25)
    assert formats.pixel_box(None, 100, 50) is None


def test_pixel_box_leaves_image_coordinates_alone():
    g = geo(50, 25, 20, 10)
    g["coordinate_type"] = "IMAGE"
    assert formats.pixel_box(g, 200, 100) == (40, 20, 60, 30)


# ---------------------------------------------------------------------- text


def test_ocr_text_from_detailed_result():
    result = make_result()
    assert formats.ocr_text(result) == "Hello <b> & co\nsecond"
    assert formats.ocr_text(result, preserve_line_breaks=False) == (
        "Hello <b> & co second"
    )
    assert formats.ocr_text({"ocr_text": "plain"}) == "plain"


# ---------------------------------------------------------------------- json


def test_json_for_one_page_is_an_object_with_pixel_boxes(page):
    record = formats.page_to_dict(page)
    parsed = json.loads(formats.format_json([record]))
    assert parsed["file"] == 'dir/we"ird.png'
    assert (parsed["width"], parsed["height"]) == (200, 100)
    assert parsed["translated_text"] == "Привет"
    assert parsed["ocr_text"] == "Hello <b> & co\nsecond"
    first_word = parsed["blocks"][0]["lines"][0]["words"][0]
    assert first_word["text"] == "Hello"
    assert first_word["bbox"] == {"left": 20, "top": 15, "width": 60, "height": 20}


def test_json_for_several_pages_is_an_array(page):
    records = [formats.page_to_dict(page), formats.error_record("x.png", "boom")]
    parsed = json.loads(formats.format_json(records))
    assert isinstance(parsed, list) and parsed[1] == {"file": "x.png", "error": "boom"}


def test_json_without_a_known_size_has_no_pixel_boxes():
    record = formats.page_to_dict(Page(file="a.png", result=make_result()))
    assert "bbox" not in record["blocks"][0]
    assert record["width"] is None


def test_jsonl_line_is_compact_and_single_line(page):
    line = formats.format_jsonl_line(formats.page_to_dict(page))
    assert "\n" not in line
    assert json.loads(line)["ocr_text"] == "Hello <b> & co\nsecond"


def test_oneline_record_has_the_fork_keys():
    parsed = json.loads(formats.oneline_record("a.png", "text [x]", None, None))
    assert list(parsed) == ["file", "ocr_text", "translated_text", "error"]
    assert parsed["ocr_text"] == "text [x]"
    assert parsed["error"] is None


# ---------------------------------------------------------------------- hocr


def test_hocr_is_well_formed_xhtml_with_the_expected_classes(page):
    root = ET.fromstring(formats.format_hocr([page]))
    assert root.tag == XHTML + "html"

    classes = {}
    for el in root.iter():
        cls = el.get("class")
        if cls:
            classes.setdefault(cls, []).append(el)
    assert len(classes["ocr_page"]) == 1
    assert len(classes["ocr_carea"]) == 1
    assert len(classes["ocr_par"]) == 1
    assert len(classes["ocr_line"]) == 2
    assert len(classes["ocrx_word"]) == 5

    page_div = classes["ocr_page"][0]
    assert "bbox 0 0 200 100" in page_div.get("title")
    assert 'image "dir/we"ird.png"' in page_div.get("title")  # parsed back unescaped

    words = classes["ocrx_word"]
    assert [w.text for w in words] == ["Hello", "<b>", "&", "co", "second"]
    assert words[0].get("title") == "bbox 20 15 80 35"
    # "co" has no box of its own, so it takes its line's
    assert words[3].get("title") == classes["ocr_line"][0].get("title")


def test_hocr_covers_several_pages(page):
    second = Page(file="b.png", result=make_result(), width=50, height=50)
    root = ET.fromstring(formats.format_hocr([page, second]))
    ids = [el.get("id") for el in root.iter() if el.get("class") == "ocr_page"]
    assert ids == ["page_1", "page_2"]


def test_hocr_and_tsv_refuse_to_guess_the_size():
    unsized = Page(file="a.png", result=make_result())
    with pytest.raises(ValueError):
        formats.format_hocr([unsized])
    with pytest.raises(ValueError):
        formats.format_tsv([unsized])


# ----------------------------------------------------------------------- tsv


def parse_tsv(text):
    return list(csv.DictReader(io.StringIO(text), delimiter="\t"))


def test_tsv_has_tesseract_columns_and_levels(page):
    text = formats.format_tsv([page])
    assert text.splitlines()[0].split("\t") == [
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
    ]
    rows = parse_tsv(text)
    assert [r["level"] for r in rows] == [
        "1",
        "2",
        "3",
        "4",
        "5",
        "5",
        "5",
        "5",
        "4",
        "5",
    ]

    page_row = rows[0]
    assert (page_row["width"], page_row["height"]) == ("200", "100")

    first = rows[4]
    assert first["text"] == "Hello"
    assert (first["left"], first["top"], first["width"], first["height"]) == (
        "20",
        "15",
        "60",
        "20",
    )
    assert (
        first["block_num"],
        first["par_num"],
        first["line_num"],
        first["word_num"],
    ) == (
        "1",
        "1",
        "1",
        "1",
    )
    assert first["conf"] == "100" and rows[1]["conf"] == "-1"


def test_tsv_text_never_breaks_the_row_structure():
    result = make_result()
    result["detailed_blocks"][0]["lines"][0]["words"][0]["text"] = "a\tb\nc"
    rows = parse_tsv(
        formats.format_tsv([Page(file="a.png", result=result, width=200, height=100)])
    )
    assert rows[4]["text"] == "a b c"
