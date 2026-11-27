"""Search with an image: the session, the requests, the URL, the command.

The flow was checked live first (chrome-lens-userscript's docs/lens-capabilities.md
and an upload from this library, 2026-11-23); these tests pin it down offline.
"""

import asyncio
import base64
import json
from typing import Any, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

import pytest

from chrome_lens_py import manage
from chrome_lens_py.core import search as lens_search
from chrome_lens_py.core.request_handler import LensRequestHandler
from chrome_lens_py.exceptions import LensAPIError
from chrome_lens_py.utils import sharex_setup
from chrome_lens_py.utils.lens_betterproto import (
    LensOverlayFilterType,
    LensOverlayInteractionRequestMetadataType,
    LensOverlayRequestId,
    LensOverlayServerRequest,
    LensOverlayServerResponse,
)
from chrome_lens_py.utils.protobufs.lens_overlay_server_pb2 import (
    LensOverlayServerClusterInfoRequest,
    LensOverlayServerClusterInfoResponse,
)

TYPES = LensOverlayInteractionRequestMetadataType


# ----------------------------------------------------------------- the URL


def query(url: str) -> dict:
    return {
        k: v[0]
        for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()
    }


def test_a_visual_search_url_is_the_one_chrome_builds():
    url = lens_search.build_search_url("SEARCH", "VSRID")
    assert url.startswith("https://www.google.com/search?")
    assert query(url) == {
        "q": "",
        "lns_mode": "un",
        "lns_fp": "1",
        "lns_surface": "42",
        "gsessionid": "SEARCH",
        "udm": "26",
        "vsrid": "VSRID",
        "source": "chrome.cr.ctxi",
    }


def test_words_make_it_multimodal_and_ai_mode_is_its_own_tab():
    with_words = query(lens_search.build_search_url("S", "V", query=" red jacket "))
    assert (with_words["q"], with_words["lns_mode"], with_words["udm"]) == (
        "red jacket",
        "mu",
        "24",
    )

    ai = query(lens_search.build_search_url("S", "V", mode="ai", query="what is it?"))
    assert (ai["q"], ai["lns_mode"], ai["udm"]) == ("what is it?", "mu", "50")


def test_language_and_dark_mode_are_optional_parameters():
    params = query(lens_search.build_search_url("S", "V", ui_language="ru", dark=True))
    assert (params["hl"], params["cs"]) == ("ru", "1")
    assert "hl" not in query(lens_search.build_search_url("S", "V"))


def test_there_is_no_shopping_mode():
    # udm=28 asked for directly opens an empty Shopping page that never sees the
    # picture; products are a tab on the visual page instead.
    with pytest.raises(ValueError):
        lens_search.build_search_url("S", "V", mode="shopping")


def test_a_text_search_needs_no_session():
    params = query(lens_search.text_search_url(" two words "))
    assert params == {
        "q": "two words",
        "lns_fp": "1",
        "lns_mode": "text",
        "lns_surface": "42",
    }


def test_vsrid_is_base64url_without_padding():
    data = bytes([0xFB, 0xFF, 0xBE, 0x01])
    encoded = lens_search.base64url(data)
    assert "=" not in encoded and "+" not in encoded and "/" not in encoded
    assert base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)) == data


def test_a_region_past_the_edge_is_clamped_to_the_picture():
    assert lens_search.clamp_region((0.9, 0.1, 0.4, 0.4)) == pytest.approx(
        (0.85, 0.15, 0.3, 0.3)
    )
    assert lens_search.clamp_region((0.5, 0.5, 0.2, 0.2)) == pytest.approx(
        (0.5, 0.5, 0.2, 0.2)
    )


# --------------------------------------------------------------- transport


def test_other_methods_sit_beside_crupload():
    sibling = LensRequestHandler._sibling
    assert (
        sibling("https://lensfrontend-pa.googleapis.com/v1/crupload", "gsessionid")
        == "https://lensfrontend-pa.googleapis.com/v1/gsessionid"
    )
    # A mirror set through LENS_ENDPOINT keeps its host and prefix.
    assert sibling("https://mirror.example/lens/v1/crupload?x=1", "gsessionid") == (
        "https://mirror.example/lens/v1/gsessionid"
    )
    assert sibling("https://x/v1/crupload", None) == "https://x/v1/crupload"


def test_the_session_request_carries_no_image():
    request = LensOverlayServerClusterInfoRequest()
    request.ParseFromString(lens_search.create_cluster_info_request())
    assert request.enable_search_session_id is True
    assert request.rendering_context.rendering_environment != 0


# ------------------------------------------------------------- the flow


class FakeHandler:
    """Lens's three answers, and a record of what was asked."""

    def __init__(self, error_type: int = 0, ids: Tuple[str, str] = ("SRV", "SRCH")):
        self.calls: List[Tuple[Optional[str], Optional[str], bytes]] = []
        self.error_type = error_type
        self.ids = ids

    async def exchange(
        self, payload: bytes, session: Any = None, path: Optional[str] = None
    ) -> bytes:
        # The session is made before gsessionid answers, so it has no ids yet.
        info = session.cluster_info if session is not None else None
        server_id = info.server_session_id if info is not None else None
        self.calls.append((path, server_id, payload))
        if path == "gsessionid":
            reply = LensOverlayServerClusterInfoResponse()
            reply.server_session_id, reply.search_session_id = self.ids
            reply.routing_info.server_address = "route-1"
            return reply.SerializeToString()
        request = LensOverlayServerRequest()
        request.ParseFromString(payload)
        response = LensOverlayServerResponse()
        if request.HasField("objects_request"):
            obj = response.objects_response.overlay_objects.add()
            obj.id = "DetectedObject-1"
            obj.geometry.bounding_box.center_x = 0.25
        elif self.error_type:
            response.error.error_type = self.error_type
        return response.SerializeToString()

    def requests(self) -> List[LensOverlayServerRequest]:
        out = []
        for path, _, payload in self.calls:
            if path is None:
                request = LensOverlayServerRequest()
                request.ParseFromString(payload)
                out.append(request)
        return out


IMAGE = lens_search.UploadedImage(data=b"JPEG", width=800, height=600)


def make(handler: FakeHandler, clock=None, crop=None) -> lens_search.ImageSearch:
    kwargs = {"clock": clock} if clock is not None else {}
    return lens_search.ImageSearch(handler, IMAGE, crop=crop, **kwargs)


def decode_vsrid(url: str) -> LensOverlayRequestId:
    raw = query(url)["vsrid"]
    request_id = LensOverlayRequestId()
    request_id.ParseFromString(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    return request_id


def test_upload_opens_a_session_first_and_uploads_inside_it():
    handler = FakeHandler()
    search = make(handler)
    asyncio.run(search.start())

    (first_path, first_session, _), (second_path, second_session, _) = handler.calls
    assert (first_path, first_session) == ("gsessionid", None)
    # The upload goes to crupload with the *server* session id.
    assert (second_path, second_session) == (None, "SRV")

    objects = handler.requests()[0].objects_request
    request_id = objects.request_context.request_id
    assert (request_id.sequence_id, request_id.image_sequence_id) == (1, 1)
    assert request_id.long_context_id == 1
    assert len(request_id.analytics_id) == 16
    assert request_id.context_id and request_id.time_usec
    assert request_id.routing_info.server_address == "route-1"
    filters = objects.request_context.client_context.client_filters.filter
    assert [f.filter_type for f in filters] == [LensOverlayFilterType.AUTO_FILTER]
    assert objects.image_data.payload.image_bytes == b"JPEG"

    assert search.objects == [
        {
            "id": "DetectedObject-1",
            "box": {
                "center_x": 0.25,
                "center_y": 0.0,
                "width": 0.0,
                "height": 0.0,
                "rotation_z": 0.0,
            },
        }
    ]
    assert search.search_session_id == "SRCH"


def test_a_whole_picture_search_and_the_url_that_names_it():
    handler = FakeHandler()
    search = make(handler)
    url = asyncio.run(search.search())

    interaction = handler.requests()[1].interaction_request
    metadata = interaction.interaction_request_metadata
    assert metadata.type == TYPES.REGION_SEARCH
    box = metadata.selection_metadata.region.region
    assert (box.center_x, box.center_y, box.width, box.height) == (0.5, 0.5, 1.0, 1.0)
    # The whole picture: the upload itself goes in as the crop.
    assert interaction.image_crop.image.image_content == b"JPEG"
    zoomed = interaction.image_crop.zoomed_crop
    assert (zoomed.parent_width, zoomed.parent_height, zoomed.zoom) == (800, 600, 1.0)

    sent = interaction.request_context.request_id
    assert sent.sequence_id == 2

    # The page is addressed by the *search* session id and a request id one
    # step past the interaction, carrying the interaction's analytics id.
    assert query(url)["gsessionid"] == "SRCH"
    named = decode_vsrid(url)
    assert named.sequence_id == 3
    assert named.analytics_id == sent.analytics_id
    assert named.uuid == sent.uuid
    assert named.routing_info.server_address == "route-1"


def test_a_region_sends_its_own_pixels():
    asked = []

    def crop(region):
        asked.append(region)
        return b"CROP"

    handler = FakeHandler()
    search = make(handler, crop=crop)
    asyncio.run(search.search(lens_search.Selection(region=(0.95, 0.5, 0.2, 0.2))))

    interaction = handler.requests()[1].interaction_request
    assert interaction.image_crop.image.image_content == b"CROP"
    clamped = (0.925, 0.5, 0.15, 0.2)
    assert asked[0] == pytest.approx(clamped)
    box = interaction.interaction_request_metadata.selection_metadata.region.region
    assert (box.center_x, box.width) == pytest.approx((clamped[0], clamped[2]))


def test_tapping_an_object_sends_its_id_and_no_pixels():
    handler = FakeHandler()
    search = make(handler)
    asyncio.run(search.search(lens_search.Selection(object_id="DetectedObject-1")))

    interaction = handler.requests()[1].interaction_request
    metadata = interaction.interaction_request_metadata
    assert metadata.type == TYPES.TAP
    assert metadata.selection_metadata.object.object_id == "DetectedObject-1"
    assert not interaction.HasField("image_crop")


def test_words_and_ai_mode_ride_on_the_interaction():
    handler = FakeHandler()
    search = make(handler)
    url = asyncio.run(search.search(mode="ai", query="  what manga is this?  "))

    metadata = handler.requests()[1].interaction_request.interaction_request_metadata
    assert metadata.query_metadata.text_query.query == "what manga is this?"
    assert (query(url)["udm"], query(url)["q"]) == ("50", "what manga is this?")


def test_each_search_on_one_upload_steps_the_sequence():
    handler = FakeHandler()
    search = make(handler)
    first = asyncio.run(search.search())
    second = asyncio.run(search.search())

    # session + upload + two interactions: one upload serves both searches.
    assert [path for path, _, _ in handler.calls] == ["gsessionid", None, None, None]
    assert (decode_vsrid(first).sequence_id, decode_vsrid(second).sequence_id) == (3, 5)


def test_an_expired_session_is_reopened_and_the_picture_uploaded_again():
    now = [0.0]
    handler = FakeHandler()
    search = make(handler, clock=lambda: now[0])
    asyncio.run(search.search())

    now[0] = lens_search.SESSION_LIFETIME  # past lifetime minus the margin
    url = asyncio.run(search.search())

    paths = [path for path, _, _ in handler.calls]
    assert paths == ["gsessionid", None, None, "gsessionid", None, None]
    assert decode_vsrid(url).sequence_id == 3  # a fresh sequence


def test_a_server_error_on_the_interaction_is_raised_not_turned_into_a_link():
    handler = FakeHandler(error_type=2)
    with pytest.raises(LensAPIError, match="Type: 2"):
        asyncio.run(make(handler).search())


def test_a_session_without_ids_is_an_error():
    handler = FakeHandler(ids=("SRV", ""))
    with pytest.raises(LensAPIError, match="search session"):
        asyncio.run(make(handler).start())


def test_a_region_and_an_object_at_once_is_refused():
    with pytest.raises(ValueError):
        lens_search.Selection(region=(0.5, 0.5, 1, 1), object_id="x")


# ---------------------------------------------------------- the command


@pytest.mark.parametrize(
    "argv, says",
    [
        (["search"], "needs an image"),
        (["search", "a.png", "b.png"], "unexpected argument"),
        (["search", "a.png", "--query", "x", "--ai", "y"], "give one of them"),
        (["search", "a.png", "--region", "1,2"], "--region takes"),
        (["search", "a.png", "--region", "0.5,0.5,0,0.2"], "--region takes"),
        (["search", "a.png", "--bogus"], "unknown option"),
    ],
)
def test_a_wrong_search_command_line_exits_64(argv, says, capsys):
    assert manage.route(argv) == ("exit", manage.EXIT_USAGE)
    assert says in capsys.readouterr().err


def test_the_command_passes_its_options_through(monkeypatch):
    from chrome_lens_py.cli import search as cli_search

    seen = {}
    monkeypatch.setattr(
        cli_search,
        "run_search",
        lambda image, **kw: seen.update(image=image, **kw) or 0,
    )
    assert manage.route(
        [
            "search",
            "shot.png",
            "--region",
            "0.5,0.5,0.4,0.4",
            "--ai",
            "why",
            "--hl",
            "ru",
        ]
    ) == ("exit", 0)
    assert seen["image"] == "shot.png"
    assert seen["region"] == (0.5, 0.5, 0.4, 0.4)
    assert (seen["ai_question"], seen["ui_language"]) == ("why", "ru")
    assert seen["open_browser"] is True and seen["as_json"] is False

    # --json is for a program reading the answer: never a browser window.
    manage.route(["search", "shot.png", "--json"])
    assert seen["open_browser"] is False and seen["as_json"] is True


@pytest.fixture
def searching(monkeypatch, tmp_path):
    """run_search with Lens and the browser replaced."""
    from chrome_lens_py.api import LensAPI
    from chrome_lens_py.cli import search as cli_search

    image = tmp_path / "shot.png"
    image.write_bytes(b"not really a png")
    calls = {"opened": [], "search": []}

    async def fake_search(self, source, **kw):
        calls["search"].append((source, kw))
        return {
            "url": "https://www.google.com/search?vsrid=X",
            "mode": kw["mode"],
            "search_session_id": "S",
            "objects": [],
        }

    monkeypatch.setattr(LensAPI, "search_image", fake_search)
    monkeypatch.setattr(
        cli_search, "_open", lambda url: calls["opened"].append(url) or True
    )
    monkeypatch.setenv("LENS_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return cli_search, str(image), calls


def test_search_prints_the_link_and_opens_it(searching, capsys):
    cli_search, image, calls = searching
    assert cli_search.run_search(image) == 0
    assert capsys.readouterr().out.strip() == "https://www.google.com/search?vsrid=X"
    assert calls["opened"] == ["https://www.google.com/search?vsrid=X"]
    assert calls["search"][0][1]["mode"] == "visual"


def test_search_asks_ai_mode_with_the_question(searching):
    cli_search, image, calls = searching
    cli_search.run_search(image, ai_question="what is it", open_browser=False)
    kw = calls["search"][0][1]
    assert (kw["mode"], kw["query"]) == ("ai", "what is it")
    assert calls["opened"] == []


def test_search_json_is_the_whole_answer_and_opens_nothing(searching, capsys):
    cli_search, image, calls = searching
    assert cli_search.run_search(image, open_browser=False, as_json=True) == 0
    assert json.loads(capsys.readouterr().out)["search_session_id"] == "S"
    assert calls["opened"] == []


def test_search_of_a_missing_file_fails_without_touching_lens(searching, capsys):
    cli_search, _, calls = searching
    assert cli_search.run_search("no-such-file.png") == 1
    assert "no such image" in capsys.readouterr().err
    assert calls["search"] == []


# ------------------------------------------------------------ ShareX


def test_sharex_search_hotkey_runs_lens_scan_search():
    config = {"Hotkeys": []}
    assert sharex_setup.apply_search_hotkey(config, "C:/lens_scan.exe") is False
    entry = config["Hotkeys"][0]
    assert entry["HotkeyInfo"]["Hotkey"] == "O, Alt, Control"
    task = entry["TaskSettings"]
    assert task["Job"] == "RectangleRegion"
    program = task["ExternalPrograms"][0]
    assert (program["Name"], program["Args"]) == ("lens-search", 'search "$input"')
    assert program["HiddenWindow"] is True


def test_sharex_search_hotkey_keeps_rebound_keys_and_repairs_a_dead_job():
    config = {"Hotkeys": []}
    sharex_setup.apply_search_hotkey(config, "C:/old/lens_scan.exe")
    config["Hotkeys"][0]["HotkeyInfo"]["Hotkey"] = "S, Alt"
    config["Hotkeys"][0]["TaskSettings"]["Job"] = "None"

    assert sharex_setup.apply_search_hotkey(config, "C:/new/lens_scan.exe") is True
    entry = config["Hotkeys"][0]
    assert entry["HotkeyInfo"]["Hotkey"] == "S, Alt"
    assert entry["TaskSettings"]["Job"] == "RectangleRegion"
    assert (
        entry["TaskSettings"]["ExternalPrograms"][0]["Path"] == "C:/new/lens_scan.exe"
    )


def test_the_ocr_and_search_hotkeys_are_told_apart():
    config = {"Hotkeys": []}
    sharex_setup.apply_lens_hotkey(config, "C:/lens_scan.exe", "X")
    sharex_setup.apply_search_hotkey(config, "C:/lens_scan.exe")
    # Refreshing one must not grab the other's entry.
    sharex_setup.apply_lens_hotkey(config, "C:/lens_scan.exe", "Y")
    names = [
        h["TaskSettings"]["ExternalPrograms"][0]["Name"] for h in config["Hotkeys"]
    ]
    assert names == ["lens", "lens-search"]
    assert (
        config["Hotkeys"][1]["TaskSettings"]["ExternalPrograms"][0]["Args"]
        == 'search "$input"'
    )


def test_describe_reports_the_search_hotkey(tmp_path, monkeypatch):
    monkeypatch.setattr(sharex_setup.sys, "platform", "win32")
    monkeypatch.setattr(sharex_setup, "get_documents_path", lambda: tmp_path)
    (tmp_path / "ShareX").mkdir()
    config = {"Hotkeys": []}
    sharex_setup.apply_search_hotkey(config, "C:/lens_scan.exe")
    (tmp_path / "ShareX" / "HotkeysConfig.json").write_text(
        json.dumps(config), encoding="utf-8"
    )

    state = sharex_setup.describe()
    assert state["configured"] is True
    assert state["search_hotkey"] == "O, Alt, Control"
    assert state["broken"] == []


def test_sharex_modes_include_search_and_all():
    assert {"search", "all"} <= set(sharex_setup.MODES)
    assert manage.route(["sharex", "--mode", "nonsense"]) == ("exit", manage.EXIT_USAGE)
