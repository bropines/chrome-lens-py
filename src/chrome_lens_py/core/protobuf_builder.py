# src/chrome_lens_py/core/protobuf_builder.py
import logging
import random
from typing import Optional, Tuple

from ..constants import (
    DEFAULT_CLIENT_REGION,
    DEFAULT_CLIENT_TIME_ZONE,
    DEFAULT_OCR_LANG,
)
from ..exceptions import LensProtobufError
from ..utils.lens_betterproto import (
    CoordinateType,
    LensOverlayFilterType,
    LensOverlayInteractionRequestMetadataType,
    LensOverlayRoutingInfo,
    LensOverlayServerRequest,
    LensRenderingEnvironment,
    Platform,
    Surface,
)

logger = logging.getLogger(__name__)


def create_ocr_translate_request(
    image_bytes: bytes,
    width: int,
    height: int,
    ocr_language: str,
    target_translation_language: Optional[str] = None,
    source_translation_language: Optional[str] = None,
    client_region: Optional[str] = None,
    client_time_zone: Optional[str] = None,
    session_uuid: Optional[int] = None,
    sequence_id: int = 1,
    image_sequence_id: int = 1,
    routing_info: Optional["LensOverlayRoutingInfo"] = None,
) -> Tuple[bytes, int]:
    try:
        server_request = LensOverlayServerRequest()

        objects_req = server_request.objects_request
        req_ctx = objects_req.request_context

        uuid_to_use = (
            session_uuid
            if session_uuid is not None
            else random.randint(0, (1 << 63) - 1)
        )

        req_ctx.request_id.uuid = uuid_to_use
        req_ctx.request_id.sequence_id = sequence_id
        req_ctx.request_id.image_sequence_id = image_sequence_id
        if routing_info:
            req_ctx.request_id.routing_info.CopyFrom(routing_info)

        client_ctx = req_ctx.client_context
        client_ctx.platform = Platform.PLATFORM_WEB
        client_ctx.surface = Surface.SURFACE_CHROMIUM
        # Chromium's shipping path pairs SURFACE_CHROMIUM/PLATFORM_WEB with this
        # rendering environment (LensOverlayQueryController::CreateClientContext).
        # Note it never sets app_id, despite the proto marking it required.
        client_ctx.rendering_context.rendering_environment = (
            LensRenderingEnvironment.RENDERING_ENV_LENS_OVERLAY
        )

        client_ctx.locale_context.language = ocr_language or DEFAULT_OCR_LANG
        client_ctx.locale_context.region = client_region or DEFAULT_CLIENT_REGION
        client_ctx.locale_context.time_zone = (
            client_time_zone or DEFAULT_CLIENT_TIME_ZONE
        )

        # Chromium always sends exactly one filter, and TRANSLATE *replaces*
        # AUTO_FILTER rather than joining it. We previously sent no filter at all
        # when not translating, which is a state real Chrome never produces.
        filter_obj = client_ctx.client_filters.filter.add()
        if target_translation_language:
            filter_obj.filter_type = LensOverlayFilterType.TRANSLATE
            filter_obj.translate.target_language = target_translation_language
            if source_translation_language:
                filter_obj.translate.source_language = source_translation_language
        else:
            filter_obj.filter_type = LensOverlayFilterType.AUTO_FILTER

        img_data = objects_req.image_data
        img_data.payload.image_bytes = image_bytes
        img_data.image_metadata.width = width
        img_data.image_metadata.height = height

        protobuf_payload_bytes = server_request.SerializeToString()

        logger.debug(
            "Protobuf request created. UUID: %s, SeqID: %s, ImgSeqID: %s, Size: %d bytes.",
            uuid_to_use,
            sequence_id,
            image_sequence_id,
            len(protobuf_payload_bytes),
        )
        return protobuf_payload_bytes, uuid_to_use

    except Exception as e:
        logger.error(f"Error creating Protobuf request: {e}", exc_info=True)
        raise LensProtobufError(f"Error while creating Protobuf request: {e}") from e


def create_region_request(
    crop_bytes: bytes,
    region: Tuple[float, float, float, float],
    parent_width: int,
    parent_height: int,
    crop_width: int,
    ocr_language: str,
    session_uuid: int,
    sequence_id: int,
    image_sequence_id: int,
    client_region: Optional[str] = None,
    client_time_zone: Optional[str] = None,
    routing_info: Optional["LensOverlayRoutingInfo"] = None,
    text_query: Optional[str] = None,
) -> bytes:
    """Build a region-scoped interaction request.

    This is the "select a region" flow. It goes to the same crupload endpoint
    as the objects request, but carries only the cropped pixels, which means
    the region is sent at far higher effective resolution than it occupies in
    the full image. That is the point: small text that the full-image pass
    reads poorly gets a second look at native scale.

    `region` is (center_x, center_y, width, height), normalized to the FULL
    image. Mirrors LensOverlayQueryController::CreateInteractionRequest.
    """
    try:
        server_request = LensOverlayServerRequest()
        interaction = server_request.interaction_request
        req_ctx = interaction.request_context

        req_ctx.request_id.uuid = session_uuid
        req_ctx.request_id.sequence_id = sequence_id
        req_ctx.request_id.image_sequence_id = image_sequence_id
        # Chromium mints a fresh 16-byte analytics id for every interaction.
        req_ctx.request_id.analytics_id = random.randbytes(16)
        if routing_info:
            req_ctx.request_id.routing_info.CopyFrom(routing_info)

        client_ctx = req_ctx.client_context
        client_ctx.platform = Platform.PLATFORM_WEB
        client_ctx.surface = Surface.SURFACE_CHROMIUM
        client_ctx.rendering_context.rendering_environment = (
            LensRenderingEnvironment.RENDERING_ENV_LENS_OVERLAY
        )
        client_ctx.locale_context.language = ocr_language or DEFAULT_OCR_LANG
        client_ctx.locale_context.region = client_region or DEFAULT_CLIENT_REGION
        client_ctx.locale_context.time_zone = (
            client_time_zone or DEFAULT_CLIENT_TIME_ZONE
        )
        client_ctx.client_filters.filter.add().filter_type = (
            LensOverlayFilterType.AUTO_FILTER
        )

        metadata = interaction.interaction_request_metadata
        metadata.type = LensOverlayInteractionRequestMetadataType.REGION_SEARCH

        center_x, center_y, region_w, region_h = region
        box = metadata.selection_metadata.region.region
        box.center_x = center_x
        box.center_y = center_y
        box.width = region_w
        box.height = region_h
        box.coordinate_type = CoordinateType.NORMALIZED

        if text_query:
            metadata.query_metadata.text_query.query = text_query

        crop = interaction.image_crop
        crop.image.image_content = crop_bytes
        zoomed = crop.zoomed_crop
        zoomed.parent_width = parent_width
        zoomed.parent_height = parent_height
        # How much the crop was scaled up relative to its size in the parent.
        region_px_width = max(1.0, region_w * parent_width)
        zoomed.zoom = crop_width / region_px_width
        zoomed.crop.center_x = center_x
        zoomed.crop.center_y = center_y
        zoomed.crop.width = region_w
        zoomed.crop.height = region_h
        zoomed.crop.coordinate_type = CoordinateType.NORMALIZED

        payload_bytes = server_request.SerializeToString()
        logger.debug(
            "Region request created. UUID: %s, SeqID: %s, region: %s, size: %d bytes.",
            session_uuid,
            sequence_id,
            region,
            len(payload_bytes),
        )
        return payload_bytes

    except Exception as e:
        logger.error(f"Error creating region request: {e}", exc_info=True)
        raise LensProtobufError(f"Error while creating region request: {e}") from e
