"""Offline tests for the pure logic.

Everything here runs without network access. The live API tests live in
test_api.py and are marked `network`.
"""

import pytest
from PIL import Image

from chrome_lens_py.cli.main import force_utf8_streams
from chrome_lens_py.core.image_processor import (
    _is_numpy_array,
    _preferred_size,
    _resize_and_serialize_pil_image,
    crop_region,
    should_downscale,
)
from chrome_lens_py.core.request_handler import LensSession, detect_env_proxy
from chrome_lens_py.core.text_renderer import (
    _argb_to_rgba,
    _is_upright,
    _u16_slice,
    _vertical_runs,
    _wrap_text,
    build_line_text,
    fit_font_size,
    wraps_per_character,
)
from chrome_lens_py.exceptions import LensImageError, LensProtobufError
from chrome_lens_py.server import (
    LensServer,
    _choice,
    _number,
    is_loopback,
    json_safe,
)

# --------------------------------------------------------------- downscaling


@pytest.mark.parametrize(
    "width,height,expected",
    [
        (1600, 900, False),  # area 1.44M: under the limit, Chromium keeps it
        (1920, 1080, True),  # area 2.07M and wider than 1600
        (3000, 100, False),  # very wide but only 0.3M pixels
        (1601, 1601, True),
        (800, 600, False),
    ],
)
def test_should_downscale_matches_chromium_rule(width, height, expected):
    assert should_downscale(width, height) is expected


def test_preferred_size_preserves_aspect_ratio():
    w, h = _preferred_size(3200, 1800)
    assert (w, h) == (1600, 900)
    assert abs((w / h) - (3200 / 1800)) < 0.01


def test_encodes_as_jpeg_and_flattens_alpha():
    image = Image.new("RGBA", (40, 30), (255, 0, 0, 0))
    data, w, h = _resize_and_serialize_pil_image(image)
    assert data[:2] == b"\xff\xd8"  # JPEG SOI
    assert (w, h) == (40, 30)


def test_is_numpy_array_without_importing_numpy():
    assert _is_numpy_array([1, 2, 3]) is False
    assert _is_numpy_array("nope") is False


# ------------------------------------------------------------------ cropping


def test_crop_region_extracts_expected_pixels():
    image = Image.new("RGB", (400, 200), (255, 255, 255))
    image.paste(Image.new("RGB", (40, 20), (0, 0, 0)), (100, 60))
    data, w, h = crop_region(image, (0.3, 0.35, 0.2, 0.2))
    assert (w, h) == (80, 40)
    assert data[:2] == b"\xff\xd8"


def test_crop_region_rejects_empty_region():
    image = Image.new("RGB", (100, 100))
    with pytest.raises(LensImageError):
        crop_region(image, (0.5, 0.5, 0.0, 0.0))


# -------------------------------------------------------------- utf-16 slicing


def test_u16_slice_matches_python_for_bmp_text():
    text = "Hello мир"
    assert _u16_slice(text, 0, 5) == "Hello"
    assert _u16_slice(text, 6, 9) == "мир"


def test_u16_slice_handles_surrogate_pairs():
    # An emoji is two UTF-16 code units but one Python code point, which is
    # exactly where naive slicing drifts against the server's offsets.
    text = "a😀b"
    assert len(text) == 3
    assert _u16_slice(text, 0, 1) == "a"
    assert _u16_slice(text, 1, 3) == "😀"
    assert _u16_slice(text, 3, 4) == "b"


def test_u16_slice_empty_range():
    assert _u16_slice("abc", 2, 2) == ""


# ------------------------------------------------------- line reconstruction


class _Word:
    def __init__(self, start, end):
        self.start, self.end = start, end


class _Line:
    def __init__(self, words):
        self.word = [_Word(s, e) for s, e in words]


def test_build_line_text_joins_words_with_gap_separators():
    translation = "one two three"
    line = _Line([(0, 3), (4, 7), (8, 13)])
    assert build_line_text(translation, line, None) == "one two three"


def test_build_line_text_takes_trailing_separator_from_next_line():
    translation = "alpha beta gamma"
    first = _Line([(0, 5), (6, 10)])
    second = _Line([(11, 16)])
    # The gap between "beta" and "gamma" belongs to the first line's last word.
    assert build_line_text(translation, first, second) == "alpha beta "


def test_build_line_text_empty_line():
    assert build_line_text("anything", _Line([]), None) == ""


# --------------------------------------------------------------- font fitting


def test_fit_font_size_shrinks_to_fit_a_narrow_box():
    _, big = fit_font_size("Hi", None, 400, 200)
    _, small = fit_font_size("Hi", None, 40, 12)
    assert big > small >= 3


def test_fit_font_size_never_exceeds_bounds():
    _, size = fit_font_size("x", None, 100000, 100000)
    assert size <= 150
    _, tiny = fit_font_size("a very long line of text indeed", None, 1, 1)
    assert tiny >= 3


# ------------------------------------------------------------ vertical layout


@pytest.mark.parametrize(
    "char,upright",
    [
        ("今", True),
        ("は", True),
        ("ア", True),
        ("한", True),
        ("A", False),
        ("7", False),
    ],
)
def test_upright_classification(char, upright):
    assert _is_upright(char) is upright


def test_vertical_runs_split_cjk_from_latin():
    runs = _vertical_runs("今日はWiFiです")
    assert [(u, t) for u, t in runs] == [
        (True, "今日は"),
        (False, "WiFi"),
        (True, "です"),
    ]


def test_vertical_runs_attach_space_to_previous_run():
    runs = _vertical_runs("今日 は")
    assert len(runs) == 1 and runs[0][0] is True


# ------------------------------------------------------------------ wrapping


def test_wrap_text_breaks_on_words():
    from PIL import ImageFont

    font = ImageFont.load_default(20)
    lines = _wrap_text("alpha beta gamma delta epsilon", font, 80)
    assert len(lines) > 1
    assert all(line.strip() for line in lines)


def test_wrap_text_breaks_between_characters_when_asked():
    from PIL import ImageFont

    font = ImageFont.load_default(20)
    lines = _wrap_text("今天天气不错今天天气不错", font, 40, per_character=True)
    assert len(lines) > 1


def test_wrap_text_never_splits_a_word_it_was_not_asked_to():
    # Deciding per-character wrapping from whether the string contained a space
    # split short Russian words letter by letter down a column.
    from PIL import ImageFont

    font = ImageFont.load_default(20)
    lines = _wrap_text("Уже", font, 8)
    assert lines == ["Уже"]


def test_wraps_per_character_follows_the_target_language():
    assert wraps_per_character("ja") is True
    assert wraps_per_character("zh-CN") is True
    assert wraps_per_character("ru") is False
    assert wraps_per_character("") is False


# -------------------------------------------------------------------- colours


def test_argb_to_rgba_channel_order():
    assert _argb_to_rgba(0xFF284678) == (0x28, 0x46, 0x78, 0xFF)
    assert _argb_to_rgba(0x00000000) == (0, 0, 0, 0)


# -------------------------------------------------------------------- session


@pytest.mark.asyncio
async def test_session_ids_advance_independently():
    session = LensSession()
    assert await session.next_ids(True) == (None, 1, 1)
    assert await session.next_ids(False) == (None, 2, 1)
    assert await session.next_ids(True) == (None, 3, 2)


@pytest.mark.asyncio
async def test_sessions_do_not_share_counters():
    first, second = LensSession(), LensSession()
    await first.next_ids(True)
    await first.next_ids(True)
    assert (await second.next_ids(True))[1] == 1


def test_detect_env_proxy(monkeypatch):
    for var in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    assert detect_env_proxy() is None
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:2080")
    assert "127.0.0.1:2080" in detect_env_proxy()


# ----------------------------------------------------------------- exceptions


def test_protobuf_error_accepts_response_body():
    # This raised TypeError before the class gained an __init__, which turned
    # every server-side error into a confusing traceback.
    err = LensProtobufError("parse failed", response_body="deadbeef")
    assert "deadbeef" in str(err)


# --------------------------------------------------------------- serialization


def test_json_safe_encodes_bytes_and_drops_raw_protobuf():
    payload = {
        "raw_response_objects": object(),
        "image": b"\x01\x02",
        "nested": [{"more": b"\xff"}],
        "text": "ok",
    }
    result = json_safe(payload)
    assert "raw_response_objects" not in result
    assert result["image"] == "AQI="
    assert result["nested"][0]["more"] == "/w=="
    assert result["text"] == "ok"


# ------------------------------------------------------------ daemon exposure
#
# These guard a property rather than a behaviour: the daemon carries an API key
# and will call Google for whoever reaches it, so it must not be reachable from
# a web page that the user merely happens to be visiting, and must not read
# this machine's disk for a remote caller. Both were true of an earlier build.


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("0.0.0.0", False),
        ("192.168.1.10", False),
    ],
)
def test_is_loopback(host, expected):
    assert is_loopback(host) is expected


def _server(**kwargs):
    return LensServer(api=None, **kwargs)


def test_public_bind_requires_a_token():
    with pytest.raises(ValueError, match="without --token"):
        _server(host="0.0.0.0")
    # With one, it is allowed.
    assert _server(host="0.0.0.0", token="s3cret").local_only is False


def test_no_cors_headers_without_an_allowed_origin():
    server = _server()
    assert server._cors_headers("https://evil.example") == {}
    assert server._cors_headers(None) == {}


def test_cors_echoes_only_the_origin_that_was_allowed():
    server = _server(allowed_origins=frozenset({"https://mine.example"}))
    assert server._cors_headers("https://evil.example") == {}
    headers = server._cors_headers("https://mine.example")
    # Never a wildcard: the echo has to be the exact origin we vetted.
    assert headers["Access-Control-Allow-Origin"] == "https://mine.example"
    assert headers["Vary"] == "Origin"


def test_remote_daemon_refuses_paths_and_urls():
    server = _server(host="0.0.0.0", token="s3cret")
    for source in ("C:/Users/me/secrets.png", "https://internal.corp/private.png"):
        with pytest.raises(ValueError, match="only accepts"):
            server._resolve_source({"image": source})
    # Inline pixels remain fine - those the caller already had.
    assert server._resolve_source({"image_b64": "AQI="}) == b"\x01\x02"


def test_local_daemon_still_accepts_a_path():
    assert _server()._resolve_source({"image": "shot.png"}) == "shot.png"


def test_choice_rejects_values_off_the_list():
    assert _choice({"erase_mode": "hull"}, "erase_mode", ("patch", "hull"), "patch")
    assert _choice({}, "erase_mode", ("patch", "hull"), "patch") == "patch"
    with pytest.raises(ValueError, match="must be one of"):
        _choice({"erase_mode": "rm -rf"}, "erase_mode", ("patch", "hull"), "patch")


def test_number_rejects_non_numbers():
    assert _number({"outline_scale": 3}, "outline_scale", 1.0) == 3.0
    with pytest.raises(ValueError, match="must be a number"):
        _number({"outline_scale": "8x"}, "outline_scale", 1.0)
    # bool is an int in Python; it is still not a scale factor.
    with pytest.raises(ValueError, match="must be a number"):
        _number({"outline_scale": True}, "outline_scale", 1.0)


# ------------------------------------------------------------- stream encoding


class _FakeStream:
    """Stands in for sys.stdout with a chosen encoding."""

    def __init__(self, encoding):
        self.encoding = encoding
        self.reconfigured_to = None

    def reconfigure(self, encoding, errors=None):
        self.reconfigured_to = encoding
        self.encoding = encoding


@pytest.mark.parametrize(
    "encoding,expected",
    [
        # A process started without LANG - launchd, cron, a Quick Action,
        # Karabiner's shell_command, a non-interactive ssh command.
        ("ANSI_X3.4-1968", "utf-8"),
        ("ascii", "utf-8"),
        ("cp1251", "utf-8"),
        # Already fine: leave it alone rather than churn the stream.
        ("utf-8", None),
        ("UTF-8", None),
        ("utf8", None),
    ],
)
def test_force_utf8_streams(encoding, expected):
    stream = _FakeStream(encoding)
    force_utf8_streams([stream])
    assert stream.reconfigured_to == expected


def test_force_utf8_streams_survives_a_stream_that_cannot_reconfigure():
    class Stubborn:
        encoding = "ascii"

        def reconfigure(self, **kwargs):
            raise AttributeError("no")

    # Printing degraded is bad; refusing to start is worse.
    force_utf8_streams([Stubborn()])
