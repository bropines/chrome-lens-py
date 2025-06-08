import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

import httpx
from PIL import ImageFont

from .constants import DEFAULT_CLIENT_REGION, DEFAULT_CLIENT_TIME_ZONE, DEFAULT_OCR_LANG
from .core.image_processor import (
    draw_overlay_on_image,
    get_word_geometry_data,
    prepare_image_for_api,
)
from .core.protobuf_builder import create_ocr_translate_request
from .core.request_handler import LensRequestHandler
from .exceptions import LensException
from .utils.font_manager import FontType, get_font

if TYPE_CHECKING:
    from .utils.lens_betterproto import (
        LensOverlayServerResponse,
        TranslationDataStatusCode,
    )
else:
    from .utils.lens_betterproto import (
        LensOverlayServerResponse,
        TranslationDataStatusCode,
    )

logger = logging.getLogger(__name__)


class LensAPI:
    def __init__(
        self,
        api_key: str,
        client_region: Optional[str] = None,
        client_time_zone: Optional[str] = None,
        proxy: Optional[Union[str, Dict[str, httpx.AsyncBaseTransport]]] = None,
        timeout: int = 60,
        font_path: Optional[str] = None,
        font_size: Optional[int] = None,
    ):
        self.request_handler = LensRequestHandler(
            api_key=api_key, proxy=proxy, timeout=timeout
        )
        self.client_region = client_region
        self.client_time_zone = client_time_zone
        self.font_path = font_path
        self.font_size = font_size
        self._font_object: Optional[FontType] = None

    def _get_font(self) -> FontType:
        if not self._font_object:
            self._font_object = get_font(
                font_path_override=self.font_path, font_size_override=self.font_size
            )
        return self._font_object

    def _extract_ocr_data_from_response(
        self,
        response_proto: "LensOverlayServerResponse",
        preserve_line_breaks: bool = True,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Extracts OCR text and detailed data for each word (text, geometry)."""
        word_data_list: List[Dict[str, Any]] = []
        if not (
            response_proto.objects_response
            and response_proto.objects_response.text
            and response_proto.objects_response.text.text_layout
        ):
            return "", []

        for paragraph in response_proto.objects_response.text.text_layout.paragraphs:
            for line in paragraph.lines:
                for word in line.words:
                    word_data_list.append(
                        {
                            "word": word.plain_text,
                            "separator": word.text_separator,
                            "geometry": (
                                get_word_geometry_data(word.geometry.bounding_box)
                                if word.geometry and word.geometry.bounding_box
                                else None
                            ),
                        }
                    )

        full_ocr_text = ""
        if preserve_line_breaks:
            # current_line_words = []
            # text_lines = []
            if word_data_list:
                full_ocr_text = "\n".join(
                    " ".join(w.plain_text for w in line.words)
                    for p in response_proto.objects_response.text.text_layout.paragraphs
                    for line in p.lines
                )
        else:
            text_parts = [
                data["word"] + (data["separator"] or "") for data in word_data_list
            ]
            full_ocr_text = "".join(text_parts).strip()
            full_ocr_text = " ".join(full_ocr_text.split())

        detected_lang = getattr(
            response_proto.objects_response.text, "content_language", "N/A"
        )
        logger.info(
            f"Extracted data for {len(word_data_list)} words. Detected language: {detected_lang}"
        )
        return full_ocr_text, word_data_list

    def _extract_translation_from_response(
        self, response_proto: "LensOverlayServerResponse"
    ) -> Optional[str]:
        """Extracts and consolidates all successful translations."""
        all_translations = []
        if (
            response_proto.objects_response
            and response_proto.objects_response.deep_gleams
        ):
            for gleam in response_proto.objects_response.deep_gleams:
                if (
                    gleam.translation
                    and gleam.translation.status.code
                    == TranslationDataStatusCode.SUCCESS
                ):
                    if gleam.translation.translation:
                        all_translations.append(gleam.translation.translation)
        return "\n".join(all_translations).strip() or None

    async def process_image(
        self,
        image_path: Any,
        ocr_language: Optional[str] = None,
        target_translation_language: Optional[str] = None,
        source_translation_language: Optional[str] = None,
        output_overlay_path: Optional[str] = None,
        new_session: bool = True,
        ocr_preserve_line_breaks: bool = True,
    ) -> Dict[str, Any]:
        """Processes an image from any source, performing OCR and optional translation."""
        if isinstance(image_path, str):
            logger.info(f"Processing image source: {image_path[:120]}...")
        else:
            logger.info(f"Processing image source of type: {type(image_path).__name__}")

        try:
            img_bytes, width, height, original_pil_img = await prepare_image_for_api(
                image_path
            )

            if new_session:
                self.request_handler.start_new_session()

            session_uuid_for_request, seq_id, img_seq_id = (
                self.request_handler.get_next_sequence_ids_for_request(
                    is_new_image_payload=new_session
                )
            )

            proto_payload, uuid_for_this_request = create_ocr_translate_request(
                image_bytes=img_bytes,
                width=width,
                height=height,
                ocr_language=ocr_language or DEFAULT_OCR_LANG,
                target_translation_language=target_translation_language,
                source_translation_language=source_translation_language,
                client_region=self.client_region or DEFAULT_CLIENT_REGION,
                client_time_zone=self.client_time_zone or DEFAULT_CLIENT_TIME_ZONE,
                session_uuid=session_uuid_for_request,
                sequence_id=seq_id,
                image_sequence_id=img_seq_id,
                routing_info=(
                    self.request_handler.last_cluster_info.routing_info
                    if self.request_handler.last_cluster_info
                    else None
                ),
            )

            response_proto = await self.request_handler.send_request(
                proto_payload, request_uuid_used=uuid_for_this_request
            )

            ocr_text, word_data = self._extract_ocr_data_from_response(
                response_proto, ocr_preserve_line_breaks
            )
            translated_text = (
                self._extract_translation_from_response(response_proto)
                if target_translation_language
                else None
            )

            if output_overlay_path and translated_text:
                word_boxes_norm = []
                for data in word_data:
                    geom = data.get("geometry")
                    if geom:
                        x1 = geom["center_x"] - geom["width"] / 2
                        y1 = geom["center_y"] - geom["height"] / 2
                        x2 = geom["center_x"] + geom["width"] / 2
                        y2 = geom["center_y"] + geom["height"] / 2
                        word_boxes_norm.append((x1, y1, x2, y2))

                overlay_image = draw_overlay_on_image(
                    original_pil_img, word_boxes_norm, translated_text, self._get_font()
                )
                try:
                    overlay_image.save(output_overlay_path)
                    logger.info(f"Image with overlay saved to: {output_overlay_path}")
                except Exception as e_save:
                    logger.error(
                        f"Error saving overlay image to '{output_overlay_path}': {e_save}"
                    )
            elif output_overlay_path:
                logger.warning(
                    f"Overlay output path '{output_overlay_path}' specified, but no translated text available."
                )

            return {
                "ocr_text": ocr_text,
                "translated_text": translated_text,
                "word_data": word_data,
                "raw_response_objects": response_proto.objects_response,
            }
        except LensException as e:
            logger.error(f"LensAPI processing error: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error in LensAPI: {e}", exc_info=True)
            raise LensException(f"Unexpected error in LensAPI: {e}") from e
