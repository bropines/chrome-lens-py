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
    LensOverlayServerRequest,
    Platform,
    Surface,
    LensOverlayFilterType,
    LensOverlayRoutingInfo
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
        
        uuid_to_use = session_uuid if session_uuid is not None else random.randint(0, (1 << 63) - 1)
        
        req_ctx.request_id.uuid = uuid_to_use
        req_ctx.request_id.sequence_id = sequence_id
        req_ctx.request_id.image_sequence_id = image_sequence_id
        if routing_info:
            req_ctx.request_id.routing_info.CopyFrom(routing_info)

        client_ctx = req_ctx.client_context
        client_ctx.platform = Platform.PLATFORM_WEB
        client_ctx.surface = Surface.SURFACE_CHROMIUM
        
        client_ctx.locale_context.language = ocr_language or DEFAULT_OCR_LANG
        client_ctx.locale_context.region = client_region or DEFAULT_CLIENT_REGION
        client_ctx.locale_context.time_zone = client_time_zone or DEFAULT_CLIENT_TIME_ZONE
        
        if target_translation_language:
            filter_obj = client_ctx.client_filters.filter.add()
            filter_obj.filter_type = LensOverlayFilterType.TRANSLATE
            filter_obj.translate.target_language = target_translation_language
            if source_translation_language:
                filter_obj.translate.source_language = source_translation_language

        img_data = objects_req.image_data
        img_data.payload.image_bytes = image_bytes
        img_data.image_metadata.width = width
        img_data.image_metadata.height = height
        
        protobuf_payload_bytes = server_request.SerializeToString()
        
        logger.debug(
            "Protobuf request created. UUID: %s, SeqID: %s, ImgSeqID: %s, Size: %d bytes.",
            uuid_to_use, sequence_id, image_sequence_id, len(protobuf_payload_bytes)
        )
        return protobuf_payload_bytes, uuid_to_use

    except Exception as e:
        logger.error(f"Error creating Protobuf request: {e}", exc_info=True)
        raise LensProtobufError(f"Error while creating Protobuf request: {e}") from e