import random
import logging
from typing import Optional, Tuple # Добавил Tuple

from ..constants import DEFAULT_CLIENT_REGION, DEFAULT_CLIENT_TIME_ZONE, DEFAULT_OCR_LANG
from ..exceptions import LensProtobufError

try:
    from ..lens_betterproto import (
        LensOverlayServerRequest, LensOverlayObjectsRequest, LensOverlayRequestContext,
        LensOverlayClientContext, LocaleContext, Platform, Surface, ImageData,
        ImagePayload, ImageMetadata, LensOverlayRequestId, AppliedFilter, AppliedFilters,
        LensOverlayFilterType, AppliedFilterTranslate, LensOverlayClusterInfo,
        LensOverlayRoutingInfo
    )
except ImportError:
    # ... (заглушки как раньше) ...
    LensOverlayServerRequest = "LensOverlayServerRequest" # type: ignore
    LensOverlayObjectsRequest = "LensOverlayObjectsRequest" # type: ignore
    LensOverlayRequestContext = "LensOverlayRequestContext" # type: ignore
    LensOverlayClientContext = "LensOverlayClientContext" # type: ignore
    LocaleContext = "LocaleContext" # type: ignore
    Platform = "Platform" # type: ignore
    Surface = "Surface" # type: ignore
    ImageData = "ImageData" # type: ignore
    ImagePayload = "ImagePayload" # type: ignore
    ImageMetadata = "ImageMetadata" # type: ignore
    LensOverlayRequestId = "LensOverlayRequestId" # type: ignore
    AppliedFilter = "AppliedFilter" # type: ignore
    AppliedFilters = "AppliedFilters" # type: ignore
    LensOverlayFilterType = "LensOverlayFilterType" # type: ignore
    AppliedFilterTranslate = "AppliedFilterTranslate" # type: ignore
    LensOverlayClusterInfo = "LensOverlayClusterInfo" # type: ignore
    LensOverlayRoutingInfo = "LensOverlayRoutingInfo" # type: ignore


logger = logging.getLogger(__name__)

def create_ocr_translate_request(
    image_bytes: bytes,
    width: int,
    height: int,
    ocr_language: Optional[str], 
    target_translation_language: Optional[str] = None,
    source_translation_language: Optional[str] = None,
    client_region: str = DEFAULT_CLIENT_REGION,
    client_time_zone: str = DEFAULT_CLIENT_TIME_ZONE,
    session_uuid: Optional[int] = None, # UUID от RequestHandler (может быть None)
    sequence_id: int = 1,
    image_sequence_id: int = 1,
    routing_info: Optional[LensOverlayRoutingInfo] = None
) -> Tuple[bytes, int]: # Возвращаем payload и использованный/сгенерированный UUID
    try:
        server_request = LensOverlayServerRequest()
        objects_request = LensOverlayObjectsRequest()
        request_context = LensOverlayRequestContext()

        # Если session_uuid не предоставлен (None), генерируем новый.
        # Иначе используем предоставленный.
        uuid_to_use = session_uuid if session_uuid is not None else random.randint(0, (1 << 63) - 1)
        if session_uuid is None:
            logger.debug(f"ProtobufBuilder: No session_uuid provided, generated new one: {uuid_to_use}")
        else:
            logger.debug(f"ProtobufBuilder: Using provided session_uuid: {uuid_to_use}")


        request_id_obj = LensOverlayRequestId(
            uuid=uuid_to_use, # Используем определенный выше uuid_to_use
            sequence_id=sequence_id,
            image_sequence_id=image_sequence_id
        )
        if routing_info:
            request_id_obj.routing_info = routing_info
        request_context.request_id = request_id_obj

        effective_ocr_lang = ocr_language if ocr_language is not None else DEFAULT_OCR_LANG
        # logger.debug(f"Effective OCR language for Protobuf request: '{effective_ocr_lang}' (empty means auto-detect).") # Уже логируется в API

        locale_ctx = LocaleContext(
            language=effective_ocr_lang,
            region=client_region,
            time_zone=client_time_zone
        )
        client_ctx = LensOverlayClientContext(
            platform=Platform.WEB,
            surface=Surface.CHROMIUM,
            locale_context=locale_ctx
        )

        if target_translation_language:
            translate_options = AppliedFilterTranslate(target_language=target_translation_language)
            if source_translation_language:
                translate_options.source_language = source_translation_language

            applied_filter_translate = AppliedFilter(
                filter_type=LensOverlayFilterType.TRANSLATE,
                translate=translate_options
            )
            client_ctx.client_filters = AppliedFilters(filter=[applied_filter_translate])
            # logger.debug(f"Translation filter enabled: to '{target_translation_language}' from '{source_translation_language or 'auto'}'") # Уже логируется в API

        request_context.client_context = client_ctx
        objects_request.request_context = request_context

        image_payload_obj = ImagePayload(image_bytes=image_bytes)
        image_metadata_obj = ImageMetadata(width=width, height=height)
        image_data_obj = ImageData(
            payload=image_payload_obj,
            image_metadata=image_metadata_obj
        )
        objects_request.image_data = image_data_obj
        server_request.objects_request = objects_request

        protobuf_payload_bytes = bytes(server_request)
        logger.debug(f"Protobuf request created. UUID: {uuid_to_use}, SeqID: {sequence_id}, ImgSeqID: {image_sequence_id}, Size: {len(protobuf_payload_bytes)} bytes.")
        return protobuf_payload_bytes, uuid_to_use # Возвращаем и payload и UUID

    except Exception as e:
        logger.error(f"Error creating Protobuf request: {e}", exc_info=True)
        raise LensProtobufError(f"Ошибка при создании Protobuf запроса: {e}")