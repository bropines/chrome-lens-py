"""Search the web with an image: the half of Lens that is not in the protobuf.

Visual matches, products and the AI Mode answer exist only as Google's results
page. Chrome uploads the picture, then opens that page with two ids that name
the upload: ``vsrid`` (a serialized request id) and ``gsessionid`` (the search
session). Google joins them server side and does not care which client made
the upload - verified by uploading from a script through a proxy and opening
the URL in an unrelated browser. So the whole job here is: open a session,
upload, describe the selection, mint the URL.

The page has to open in the user's own browser. A headless browser, a fresh
profile or an embedded web view gets Google's "unusual traffic" reCAPTCHA
instead of results, so this module builds URLs and never fetches them.

The flow is Chromium's (LensOverlayQueryController, LensOverlayRequestIdGenerator,
lens_overlay_url_builder.cc), checked live in chrome-lens-userscript first; its
docs/lens-capabilities.md has the source map.
"""

import asyncio
import random
import time
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from ..constants import (
    DEFAULT_CLIENT_REGION,
    DEFAULT_CLIENT_TIME_ZONE,
    DEFAULT_OCR_LANG,
)
from ..exceptions import LensAPIError, LensIdentityRejected, LensProtobufError
from ..utils.lens_betterproto import (
    CoordinateType,
    LensOverlayClusterInfo,
    LensOverlayFilterType,
    LensOverlayInteractionRequestMetadataType,
    LensOverlayRequestId,
    LensOverlayServerRequest,
    LensOverlayServerResponse,
    LensRenderingEnvironment,
    Platform,
    Surface,
)
from ..utils.protobufs.lens_overlay_server_pb2 import (
    LensOverlayServerClusterInfoRequest,
    LensOverlayServerClusterInfoResponse,
)

RESULTS_URL = "https://www.google.com/search"
CLUSTER_INFO_PATH = "gsessionid"

# Chromium's `cluster-info-lifetime-seconds`; past it the ids stop resolving.
SESSION_LIFETIME = 1800.0
# So a URL is never minted from a session about to expire.
SESSION_MARGIN = 60.0

# `visual`: Lens results - visual matches, exact matches, an AI overview.
# `ai`: AI Mode, with the picture attached and the query as the question.
#
# There is no `shopping`. Chrome's udm=28 is a tab reached from inside the
# visual results; asked for directly with a fresh vsrid it opens an empty
# Google Shopping page that never sees the picture (tried, 2026-11-23).
# Products are one tap away on the visual page instead.
SEARCH_MODES = ("visual", "ai")

_WHOLE = (0.5, 0.5, 1.0, 1.0)


@dataclass(frozen=True)
class Selection:
    """What to search for inside an uploaded picture.

    ``region`` is (center_x, center_y, width, height), normalized 0..1 against
    the whole picture - the same shape ``process_region`` takes. ``object_id``
    is one of the ids in ``ImageSearch.objects``.
    """

    region: Optional[Tuple[float, float, float, float]] = None
    object_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.region is not None and self.object_id is not None:
            raise ValueError("Search a region or an object, not both.")


def base64url(data: bytes) -> str:
    """base64url without padding, which is how Chromium writes ``vsrid``."""
    return urlsafe_b64encode(data).decode("ascii").rstrip("=")


def clamp_region(
    region: Tuple[float, float, float, float],
) -> Tuple[float, float, float, float]:
    """Clamp a box to the picture, so a drag past the edge still means something."""
    center_x, center_y, width, height = region
    x0, y0 = max(0.0, center_x - width / 2), max(0.0, center_y - height / 2)
    x1, y1 = min(1.0, center_x + width / 2), min(1.0, center_y + height / 2)
    return ((x0 + x1) / 2, (y0 + y1) / 2, max(0.0, x1 - x0), max(0.0, y1 - y0))


def _common_params(
    params: Dict[str, str], ui_language: Optional[str], dark: Optional[bool]
) -> Dict[str, str]:
    if ui_language:
        params["hl"] = ui_language
    if dark is not None:
        params["cs"] = "1" if dark else "0"
    return params


def build_search_url(
    search_session_id: str,
    vsrid: str,
    mode: str = "visual",
    query: Optional[str] = None,
    ui_language: Optional[str] = None,
    dark: Optional[bool] = None,
) -> str:
    """The results URL, as Chromium's ``BuildLensSearchURL`` builds it.

    ``gsessionid`` here is the *search* session id; the server one only ever
    goes on crupload. The logging parameters (vsint, plla, qsubts, cud) are
    left out: the page renders without them.
    """
    if mode not in SEARCH_MODES:
        raise ValueError(f"mode must be one of {SEARCH_MODES}, not {mode!r}")
    words = (query or "").strip()
    multimodal = bool(words) or mode == "ai"
    params = {
        "q": words,
        "lns_mode": "mu" if multimodal else "un",
        "lns_fp": "1",
        "lns_surface": "42",
        "gsessionid": search_session_id,
        "udm": "50" if mode == "ai" else ("24" if multimodal else "26"),
        "vsrid": vsrid,
        "source": "chrome.cr.ctxi",
    }
    return f"{RESULTS_URL}?{urlencode(_common_params(params, ui_language, dark))}"


def text_search_url(
    words: str, ui_language: Optional[str] = None, dark: Optional[bool] = None
) -> str:
    """A plain text search, as Chrome sends one for selected words.

    Chromium's ``BuildTextOnlySearchURL``: no upload and no session - the words
    are the query, and the lns_* parameters only say where it came from.
    """
    params = {
        "q": words.strip(),
        "lns_fp": "1",
        "lns_mode": "text",
        "lns_surface": "42",
    }
    return f"{RESULTS_URL}?{urlencode(_common_params(params, ui_language, dark))}"


@dataclass
class _RequestId:
    uuid: int
    sequence_id: int
    image_sequence_id: int
    analytics_id: bytes
    context_id: int


def _fill_request_id(
    target: LensOverlayRequestId,
    ids: _RequestId,
    routing_info: Optional[Any],
) -> None:
    target.uuid = ids.uuid
    target.sequence_id = ids.sequence_id
    target.image_sequence_id = ids.image_sequence_id
    target.analytics_id = ids.analytics_id
    # The initial request bumps long_context_id to 1 and nothing after it does.
    target.long_context_id = 1
    if routing_info is not None:
        target.routing_info.CopyFrom(routing_info)
    target.time_usec = int(time.time() * 1_000_000)
    target.context_id = ids.context_id


def request_id_bytes(ids: _RequestId, routing_info: Optional[Any]) -> bytes:
    request_id = LensOverlayRequestId()
    _fill_request_id(request_id, ids, routing_info)
    return request_id.SerializeToString()


def _fill_client_context(
    client_ctx: Any,
    ocr_language: Optional[str],
    client_region: Optional[str],
    client_time_zone: Optional[str],
) -> None:
    client_ctx.platform = Platform.PLATFORM_WEB
    client_ctx.surface = Surface.SURFACE_CHROMIUM
    client_ctx.rendering_context.rendering_environment = (
        LensRenderingEnvironment.RENDERING_ENV_LENS_OVERLAY
    )
    client_ctx.locale_context.language = ocr_language or DEFAULT_OCR_LANG
    client_ctx.locale_context.region = client_region or DEFAULT_CLIENT_REGION
    client_ctx.locale_context.time_zone = client_time_zone or DEFAULT_CLIENT_TIME_ZONE
    # A search asks for no translation: exactly one filter, AUTO_FILTER.
    client_ctx.client_filters.filter.add().filter_type = (
        LensOverlayFilterType.AUTO_FILTER
    )


def create_cluster_info_request() -> bytes:
    """Open a search session: the one request that carries no image."""
    request = LensOverlayServerClusterInfoRequest()
    request.enable_search_session_id = True
    request.surface = Surface.SURFACE_CHROMIUM
    request.platform = Platform.PLATFORM_WEB
    request.rendering_context.rendering_environment = (
        LensRenderingEnvironment.RENDERING_ENV_LENS_OVERLAY
    )
    return request.SerializeToString()


def _box(target: Any, region: Tuple[float, float, float, float]) -> None:
    target.center_x, target.center_y, target.width, target.height = region
    target.coordinate_type = CoordinateType.NORMALIZED


@dataclass
class UploadedImage:
    """What the objects request needs: the encoded upload and its size."""

    data: bytes
    width: int
    height: int
    mime_type: Optional[str] = None


class ImageSearch:
    """One picture, uploaded into one search session, ready to be searched.

    ``start`` costs two requests (the session and the picture); every
    ``search`` after it costs one. A session that has expired is reopened and
    the picture uploaded again without the caller having to notice.

    ``crop`` turns a normalized region into the JPEG bytes of the selected
    pixels. It is supplied by the caller because it needs the decoded original,
    which this module deliberately knows nothing about; it is run in a worker
    thread.
    """

    def __init__(
        self,
        handler: Any,
        image: UploadedImage,
        crop: Optional[Callable[[Tuple[float, float, float, float]], bytes]] = None,
        ocr_language: Optional[str] = None,
        client_region: Optional[str] = None,
        client_time_zone: Optional[str] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._handler = handler
        self._image = image
        self._crop = crop
        self._ocr_language = ocr_language
        self._client_region = client_region
        self._client_time_zone = client_time_zone
        self._clock = clock
        self._session: Optional[Any] = None
        self._search_session_id = ""
        self._opened_at = 0.0
        self._uuid = 0
        self._context_id = 0
        self._sequence = 0
        self.objects: List[Dict[str, Any]] = []
        self.response: Optional[LensOverlayServerResponse] = None

    # --------------------------------------------------------------- state

    @property
    def fresh(self) -> bool:
        """Whether the session behind this upload is still good."""
        return self._session is not None and (
            self._clock() - self._opened_at < SESSION_LIFETIME - SESSION_MARGIN
        )

    @property
    def search_session_id(self) -> str:
        return self._search_session_id

    @property
    def signed_in(self) -> bool:
        """Whether the session was opened signed in to a Google account."""
        return bool(self._session is not None and self._session.signed)

    def _next_id(self, analytics_id: bytes) -> _RequestId:
        self._sequence += 1
        return _RequestId(
            uuid=self._uuid,
            sequence_id=self._sequence,
            image_sequence_id=1,
            analytics_id=analytics_id,
            context_id=self._context_id,
        )

    def _routing_info(self) -> Optional[Any]:
        info = self._session.cluster_info if self._session is not None else None
        return (
            info.routing_info
            if info is not None and info.HasField("routing_info")
            else None
        )

    # ------------------------------------------------------------ requests

    async def _open_session(self) -> None:
        from .request_handler import LensSession

        # Made first and passed along, so the session is pinned to whichever
        # host answers: signed in, or anonymous after a refusal.
        session = LensSession()
        self._session = None
        body = await self._handler.exchange(
            create_cluster_info_request(), session, path=CLUSTER_INFO_PATH
        )
        response = LensOverlayServerClusterInfoResponse()
        try:
            response.ParseFromString(body)
        except Exception as e:
            raise LensProtobufError(
                f"Could not read the search session reply: {e}"
            ) from e
        if not response.server_session_id or not response.search_session_id:
            raise LensAPIError("Lens did not open a search session.")

        # LensOverlayClusterInfo is what the transport reads gsessionid from.
        # Its routing_info is field 6 against the reply's 3, so fields are
        # copied by name rather than the reply reused as is.
        info = LensOverlayClusterInfo()
        info.server_session_id = response.server_session_id
        info.search_session_id = response.search_session_id
        if response.HasField("routing_info"):
            info.routing_info.CopyFrom(response.routing_info)

        session.cluster_info = info
        self._session = session
        self._search_session_id = response.search_session_id
        self._opened_at = self._clock()

    async def start(self) -> None:
        """Open a session and upload the picture into it."""
        try:
            await self._start()
        except LensIdentityRejected:
            # Signed in at gsessionid, refused at the upload. The handler is
            # anonymous from here on, so a second go opens an anonymous session.
            self._session = None
            await self._start()

    async def _start(self) -> None:
        await self._open_session()
        self._uuid = random.randint(0, (1 << 63) - 1)
        self._context_id = random.randint(0, (1 << 63) - 1)
        self._sequence = 0
        ids = self._next_id(random.randbytes(16))

        request = LensOverlayServerRequest()
        objects = request.objects_request
        _fill_request_id(objects.request_context.request_id, ids, self._routing_info())
        if self._image.mime_type:
            objects.request_context.request_id.mime_type = self._image.mime_type
        _fill_client_context(
            objects.request_context.client_context,
            self._ocr_language,
            self._client_region,
            self._client_time_zone,
        )
        objects.image_data.payload.image_bytes = self._image.data
        objects.image_data.image_metadata.width = self._image.width
        objects.image_data.image_metadata.height = self._image.height

        body = await self._handler.exchange(request.SerializeToString(), self._session)
        self.response = _parse(body)
        self.objects = [
            {"id": item.id, "box": _box_dict(item.geometry.bounding_box)}
            for item in self.response.objects_response.overlay_objects
            if item.id
        ]

    def _interaction(
        self,
        ids: _RequestId,
        selection: Selection,
        query: str,
        crop_bytes: Optional[bytes],
    ) -> bytes:
        request = LensOverlayServerRequest()
        interaction = request.interaction_request
        _fill_request_id(
            interaction.request_context.request_id, ids, self._routing_info()
        )
        _fill_client_context(
            interaction.request_context.client_context,
            self._ocr_language,
            self._client_region,
            self._client_time_zone,
        )

        metadata = interaction.interaction_request_metadata
        types = LensOverlayInteractionRequestMetadataType
        if selection.object_id is not None:
            metadata.type = types.TAP
            metadata.selection_metadata.object.object_id = selection.object_id
        else:
            box = clamp_region(selection.region) if selection.region else _WHOLE
            metadata.type = types.REGION_SEARCH
            _box(metadata.selection_metadata.region.region, box)

            # The selected pixels, as Chrome sends them: the crop at its own
            # resolution when there is a region, the upload itself otherwise.
            crop = interaction.image_crop
            crop.image.image_content = crop_bytes or self._image.data
            zoomed = crop.zoomed_crop
            _box(zoomed.crop, box)
            zoomed.parent_width = self._image.width
            zoomed.parent_height = self._image.height
            zoomed.zoom = 1.0

        if query:
            metadata.query_metadata.text_query.query = query
        return request.SerializeToString()

    async def search(
        self,
        selection: Optional[Selection] = None,
        mode: str = "visual",
        query: Optional[str] = None,
        ui_language: Optional[str] = None,
        dark: Optional[bool] = None,
    ) -> str:
        """Describe a selection to Lens and return the results URL for it.

        Chrome builds the URL as soon as the interaction is *sent*, but the
        page resolves ``vsrid`` against that interaction, so this waits for its
        answer: opening the page first would race the request it names.
        """
        if mode not in SEARCH_MODES:
            raise ValueError(f"mode must be one of {SEARCH_MODES}, not {mode!r}")
        if not self.fresh:
            await self.start()
        selection = selection or Selection()
        words = (query or "").strip()

        # Cropping decodes and re-encodes pixels: off the event loop, so a
        # daemon serving other requests does not stall on it.
        crop_bytes = None
        if selection.region and selection.object_id is None and self._crop is not None:
            crop_bytes = await asyncio.to_thread(
                self._crop, clamp_region(selection.region)
            )

        try:
            return await self._search(
                selection, mode, words, crop_bytes, ui_language, dark
            )
        except LensIdentityRejected:
            # The signed session went bad between the upload and now: upload
            # again into an anonymous one and ask once more.
            self._session = None
            await self.start()
            return await self._search(
                selection, mode, words, crop_bytes, ui_language, dark
            )

    async def _search(
        self,
        selection: Selection,
        mode: str,
        words: str,
        crop_bytes: Optional[bytes],
        ui_language: Optional[str],
        dark: Optional[bool],
    ) -> str:
        analytics_id = random.randbytes(16)
        interaction_ids = self._next_id(analytics_id)
        body = await self._handler.exchange(
            self._interaction(interaction_ids, selection, words, crop_bytes),
            self._session,
        )
        response = _parse(body)
        if response.HasField("error") and response.error.error_type != 0:
            raise LensAPIError(
                f"Lens API server error. Type: {response.error.error_type}"
            )

        # RequestIdUpdateMode::kSearchUrl: one more sequence step, the same
        # analytics id as the interaction it names.
        url_ids = self._next_id(analytics_id)
        vsrid = base64url(request_id_bytes(url_ids, self._routing_info()))
        return build_search_url(
            self._search_session_id, vsrid, mode, words, ui_language, dark
        )


def _parse(body: bytes) -> LensOverlayServerResponse:
    response = LensOverlayServerResponse()
    try:
        response.ParseFromString(body)
    except Exception as e:
        raise LensProtobufError(f"Could not read Lens's reply: {e}") from e
    return response


def _box_dict(box: Any) -> Dict[str, float]:
    """A detected object's box, normalized, in the shape the rest of the API uses."""
    return {
        "center_x": box.center_x,
        "center_y": box.center_y,
        "width": box.width,
        "height": box.height,
        "rotation_z": box.rotation_z,
    }
