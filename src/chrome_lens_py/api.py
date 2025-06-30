import asyncio
import logging
from math import pi
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Tuple, Union

import httpx
from PIL import ImageFont

from .constants import (
    DEFAULT_API_KEY,
    DEFAULT_CLIENT_REGION,
    DEFAULT_CLIENT_TIME_ZONE,
    DEFAULT_OCR_LANG,
)
from .core.image_processor import (
    draw_overlay_on_image,
    get_word_geometry_data,
    prepare_image_for_api,
)
from .core.protobuf_builder import create_ocr_translate_request
from .core.request_handler import LensRequestHandler
from .exceptions import LensException

if TYPE_CHECKING:
    from .utils.lens_betterproto import (
        LensOverlayServerResponse,
        TextLayoutParagraph,
        TranslationDataStatusCode,
    )
else:
    from .utils.lens_betterproto import (
        LensOverlayServerResponse,
        TranslationDataStatusCode,
        TextLayoutParagraph,
    )

from .utils.font_manager import FontType, get_font

logger = logging.getLogger(__name__)


class LensAPI:
    """
    Main class for interacting with the Google Lens API.
    Provides methods for OCR, translation, and text block segmentation.
    """

    def __init__(
        self,
        api_key: str = DEFAULT_API_KEY,
        client_region: Optional[str] = None,
        client_time_zone: Optional[str] = None,
        proxy: Optional[Union[str, Dict[str, httpx.AsyncBaseTransport]]] = None,
        timeout: int = 60,
        font_path: Optional[str] = None,
        font_size: Optional[int] = None,
        max_concurrent: int = 10,
    ):
        """
        Initializes the LensAPI client.

        :param api_key: Your Google API key. Defaults to the library's built-in key.
        :param client_region: ISO 3166-1 alpha-2 country code (e.g., 'US', 'DE').
        :param client_time_zone: Time zone name (e.g., 'America/New_York').
        :param proxy: Proxy server URL or a dictionary for mounting transports.
        :param timeout: Request timeout in seconds.
        :param font_path: Path to a custom .ttf font file for text overlays.
        :param font_size: Font size for text overlays.
        :param max_concurrent: The maximum number of concurrent requests to prevent API abuse. Defaults to 5.
        """
        self.request_handler = LensRequestHandler(
            api_key=api_key, proxy=proxy, timeout=timeout
        )
        self.client_region = client_region
        self.client_time_zone = client_time_zone
        self.font_path = font_path
        self.font_size = font_size
        self._font_object: Optional[FontType] = None
        self._semaphore = asyncio.Semaphore(max_concurrent)
        if max_concurrent > 20:
            logger.warning(
                f"max_concurrent is set to {max_concurrent}, which is very high. "
                "This may lead to IP bans. Use with caution."
            )

    def _get_font(self) -> FontType:
        """Lazily loads and returns the font object."""
        if not self._font_object:
            self._font_object = get_font(
                font_path_override=self.font_path, font_size_override=self.font_size
            )
        return self._font_object

    def _parse_paragraph(self, paragraph: "TextLayoutParagraph") -> Dict[str, Any]:
        """Parses a single TextLayoutParagraph into a structured dictionary."""
        paragraph_lines = []
        for line in paragraph.lines:
            # Fixed Pylance issue: use 'or ""' to handle optional separator
            current_line_text = "".join(
                word.plain_text + (word.text_separator or "") for word in line.words
            )
            paragraph_lines.append(current_line_text.strip())

        full_paragraph_text = "\n".join(paragraph_lines)

        p_geom = paragraph.geometry.bounding_box
        geometry_dict = {
            "center_x": p_geom.center_x,
            "center_y": p_geom.center_y,
            "width": p_geom.width,
            "height": p_geom.height,
            "angle_deg": p_geom.rotation_z * (180 / pi) if p_geom.rotation_z else 0.0,
        }

        return {
            "text": full_paragraph_text,
            "lines": paragraph_lines,
            "geometry": geometry_dict,
        }

    def _extract_ocr_data_from_response(
        self,
        response_proto: "LensOverlayServerResponse",
        preserve_line_breaks: bool = True,
        output_format: Literal["full_text", "blocks"] = "full_text",
    ) -> Tuple[Union[str, List[Dict]], List[Dict[str, Any]]]:
        """
        Extracts OCR data from the response.
        """
        word_data_list: List[Dict[str, Any]] = []
        if not (
            response_proto.objects_response
            and response_proto.objects_response.text
            and response_proto.objects_response.text.text_layout
        ):
            return ("", []) if output_format == "full_text" else ([], [])

        text_layout = response_proto.objects_response.text.text_layout

        for paragraph in text_layout.paragraphs:
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

        detected_lang = getattr(
            response_proto.objects_response.text, "content_language", "N/A"
        )
        logger.info(
            f"Extracted data for {len(word_data_list)} words. Detected language: {detected_lang}"
        )

        if output_format == "blocks":
            text_blocks = [self._parse_paragraph(p) for p in text_layout.paragraphs]
            return text_blocks, word_data_list
        else:  # 'full_text'
            if preserve_line_breaks:
                full_ocr_text = "\n".join(
                    "\n".join(self._parse_paragraph(p)["lines"])
                    for p in text_layout.paragraphs
                )
            else:
                text_parts = [
                    data["word"] + (data["separator"] or "") for data in word_data_list
                ]
                full_ocr_text = "".join(text_parts).strip()
                full_ocr_text = " ".join(full_ocr_text.split())

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
        output_format: Literal["full_text", "blocks"] = "full_text",
    ) -> Dict[str, Any]:
        """
        Processes an image, performing OCR and optional translation.

        :param image_path: Path to a file (str or pathlib.Path), URL, bytes, PIL Image, or NumPy array.
        :param ocr_language: BCP 47 language code for OCR (e.g., 'en', 'ja').
        :param target_translation_language: BCP 47 language code for translation target.
        :param source_translation_language: BCP 47 language code for translation source.
        :param output_overlay_path: Path to save the image with translated text overlaid.
        :param new_session: If True, starts a new server session for the request.
        :param ocr_preserve_line_breaks: If True and output_format is 'full_text', preserves line breaks.
        :param output_format: 'full_text' (default) returns a single string in 'ocr_text'.
                            'blocks' returns a list of dictionaries in 'text_blocks',
                            each representing a segmented text block.
        :return: A dictionary containing the processing results.
        """
        # Acquire the semaphore before starting any processing
        async with self._semaphore:
            if isinstance(image_path, Path):
                image_path = str(image_path)

            if isinstance(image_path, str):
                logger.info(f"Processing image source: {image_path[:120]}...")
            else:
                logger.info(
                    f"Processing image source of type: {type(image_path).__name__}"
                )

            try:
                img_bytes, width, height, original_pil_img = (
                    await prepare_image_for_api(image_path)
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

                ocr_result, word_data = self._extract_ocr_data_from_response(
                    response_proto, ocr_preserve_line_breaks, output_format
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
                        original_pil_img,
                        word_boxes_norm,
                        translated_text,
                        self._get_font(),
                    )
                    try:
                        overlay_image.save(output_overlay_path)
                        logger.info(
                            f"Image with overlay saved to: {output_overlay_path}"
                        )
                    except Exception as e_save:
                        logger.error(
                            f"Error saving overlay image to '{output_overlay_path}': {e_save}"
                        )
                elif output_overlay_path:
                    logger.warning(
                        f"Overlay output path '{output_overlay_path}' specified, but no translated text available."
                    )

                final_result = {
                    "translated_text": translated_text,
                    "word_data": word_data,
                    "raw_response_objects": response_proto.objects_response,
                }

                if output_format == "blocks":
                    final_result["text_blocks"] = ocr_result
                else:
                    final_result["ocr_text"] = ocr_result

                return final_result

            except LensException as e:
                logger.error(f"LensAPI processing error: {e}", exc_info=True)
                raise
            except Exception as e:
                logger.error(f"Unexpected error in LensAPI: {e}", exc_info=True)
                raise LensException(f"Unexpected error in LensAPI: {e}") from e
