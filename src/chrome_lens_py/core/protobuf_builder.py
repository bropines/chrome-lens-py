import logging
import random
from typing import TYPE_CHECKING, Optional, Tuple

from ..constants import (
    DEFAULT_CLIENT_REGION,
    DEFAULT_CLIENT_TIME_ZONE,
    DEFAULT_OCR_LANG,
)
from ..exceptions import LensProtobufError

if TYPE_CHECKING:
    from ..utils.lens_betterproto import (
        AppliedFilter,
        AppliedFilters,
        AppliedFilterTranslate,
        ImageData,
        ImageMetadata,
        ImagePayload,
        LensOverlayClientContext,
        LensOverlayClusterInfo,
        LensOverlayFilterType,
        LensOverlayObjectsRequest,
        LensOverlayRequestContext,
        LensOverlayRequestId,
        LensOverlayRoutingInfo,
        LensOverlayServerRequest,
        LocaleContext,
        Platform,
        Surface,
    )
else:
    from ..utils.lens_betterproto import (
        AppliedFilter,
        AppliedFilters,
        AppliedFilterTranslate,
        ImageData,
        ImageMetadata,
        ImagePayload,
        LensOverlayClientContext,
        LensOverlayClusterInfo,
        LensOverlayFilterType,
        LensOverlayObjectsRequest,
        LensOverlayRequestContext,
        LensOverlayRequestId,
        LensOverlayRoutingInfo,
        LensOverlayServerRequest,
        LocaleContext,
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
        objects_request = LensOverlayObjectsRequest()
        request_context = LensOverlayRequestContext()

        uuid_to_use = (
            session_uuid
            if session_uuid is not None
            else random.randint(0, (1 << 63) - 1)
        )
        if session_uuid is None:
            logger.debug(
                f"ProtobufBuilder: No session_uuid provided, generated new one: {uuid_to_use}"
            )
        else:
            logger.debug(f"ProtobufBuilder: Using provided session_uuid: {uuid_to_use}")

        request_id_obj = LensOverlayRequestId(
            uuid=uuid_to_use,
            sequence_id=sequence_id,
            image_sequence_id=image_sequence_id,
        )
        if routing_info:
            request_id_obj.routing_info = routing_info
        request_context.request_id = request_id_obj

        effective_client_region = (
            client_region if client_region is not None else DEFAULT_CLIENT_REGION
        )
        effective_client_time_zone = (
            client_time_zone
            if client_time_zone is not None
            else DEFAULT_CLIENT_TIME_ZONE
        )

        locale_ctx = LocaleContext(
            language=ocr_language,
            region=effective_client_region,
            time_zone=effective_client_time_zone,
        )
        client_ctx = LensOverlayClientContext(
            platform=Platform.WEB, surface=Surface.CHROMIUM, locale_context=locale_ctx
        )

        if target_translation_language:
            translate_options = AppliedFilterTranslate(
                target_language=target_translation_language
            )
            if source_translation_language:
                translate_options.source_language = source_translation_language

            applied_filter_translate = AppliedFilter(
                filter_type=LensOverlayFilterType.TRANSLATE, translate=translate_options
            )
            client_ctx.client_filters = AppliedFilters(
                filter=[applied_filter_translate]
            )

        request_context.client_context = client_ctx
        objects_request.request_context = request_context

        image_payload_obj = ImagePayload(image_bytes=image_bytes)
        image_metadata_obj = ImageMetadata(width=width, height=height)
        image_data_obj = ImageData(
            payload=image_payload_obj, image_metadata=image_metadata_obj
        )
        objects_request.image_data = image_data_obj
        server_request.objects_request = objects_request

        protobuf_payload_bytes = bytes(server_request)
        logger.debug(
            "Protobuf request created. UUID: %s, SeqID: %s, ImgSeqID: %s, Size: %d bytes.",
            uuid_to_use,
            sequence_id,
            image_sequence_id,
            len(protobuf_payload_bytes),
        )
        return protobuf_payload_bytes, uuid_to_use

    except TypeError as te:
        logger.error(f"TypeError during Protobuf request creation: {te}", exc_info=True)
        raise LensProtobufError(
            f"Type error when creating a Protobuf request: {te}"
        ) from te
    except Exception as e:
        logger.error(f"Error creating Protobuf request: {e}", exc_info=True)
        raise LensProtobufError(f"Error while creating Protobuf request: {e}") from e
