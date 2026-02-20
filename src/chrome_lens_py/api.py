# src/chrome_lens_py/api.py
import asyncio
import logging
import random
from math import pi
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import httpx

from .constants import (
    DEFAULT_API_KEY,
    DEFAULT_CLIENT_REGION,
    DEFAULT_CLIENT_TIME_ZONE,
    DEFAULT_OCR_LANG,
    LENS_CRUPLOAD_ENDPOINT
)
from .core.image_processor import (
    draw_overlay_on_image,
    get_word_geometry_data,
    prepare_image_for_api,
)
from .core.protobuf_builder import create_ocr_translate_request
from .core.request_handler import LensRequestHandler
from .exceptions import LensException
from .utils.lens_betterproto import (
    LensOverlayServerResponse,
    TextLayoutLine,
    TextLayoutParagraph,
    TextLayoutWord,
    TranslationDataStatusCode,
)
from .utils.font_manager import FontType, get_font

logger = logging.getLogger(__name__)

class LensAPI:
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
        self.request_handler = LensRequestHandler(
            api_key=api_key, proxy=proxy, timeout=timeout
        )
        self.client_region = client_region
        self.client_time_zone = client_time_zone
        self.font_path = font_path
        self.font_size = font_size
        self._font_object: Optional[FontType] = None
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def _get_font(self) -> FontType:
        if not self._font_object:
            self._font_object = get_font(
                font_path_override=self.font_path, font_size_override=self.font_size
            )
        return self._font_object

    def _parse_line(self, line: "TextLayoutLine") -> Dict[str, Any]:
        # В стандартном protobuf строки по дефолту "", а не None
        line_text = "".join(
            word.plain_text + word.text_separator for word in line.words
        ).strip()

        l_geom = line.geometry.bounding_box
        geometry_dict = {
            "center_x": l_geom.center_x,
            "center_y": l_geom.center_y,
            "width": l_geom.width,
            "height": l_geom.height,
            "angle_deg": l_geom.rotation_z * (180 / pi) if l_geom.rotation_z else 0.0,
        }

        return {
            "text": line_text,
            "geometry": geometry_dict,
        }

    def _parse_paragraph(self, paragraph: "TextLayoutParagraph") -> Dict[str, Any]:
        paragraph_lines = []
        for line in paragraph.lines:
            current_line_text = "".join(
                word.plain_text + word.text_separator for word in line.words
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

    def _parse_word_detailed(self, word: "TextLayoutWord") -> Dict[str, Any]:
        geometry_data = (
            get_word_geometry_data(word.geometry.bounding_box)
            if word.HasField("geometry") and word.geometry.HasField("bounding_box")
            else None
        )
        return {
            "text": word.plain_text,
            "separator": word.text_separator,
            "geometry": geometry_data,
        }

    def _parse_line_detailed(self, line: "TextLayoutLine") -> Dict[str, Any]:
        line_text = "".join(
            word.plain_text + word.text_separator for word in line.words
        ).strip()

        l_geom = line.geometry.bounding_box
        geometry_dict = {
            "center_x": l_geom.center_x,
            "center_y": l_geom.center_y,
            "width": l_geom.width,
            "height": l_geom.height,
            "angle_deg": l_geom.rotation_z * (180 / pi) if l_geom.rotation_z else 0.0,
        }

        return {
            "text": line_text,
            "geometry": geometry_dict,
            "words": [self._parse_word_detailed(word) for word in line.words],
        }

    def _parse_paragraph_detailed(self, paragraph: "TextLayoutParagraph") -> Dict[str, Any]:
        full_paragraph_text = "\n".join(
            "".join(
                word.plain_text + word.text_separator for word in line.words
            ).strip()
            for line in paragraph.lines
        )

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
            "geometry": geometry_dict,
            "lines": [self._parse_line_detailed(line) for line in paragraph.lines],
        }

    def _extract_ocr_data_from_response(
        self,
        response_proto: "LensOverlayServerResponse",
        preserve_line_breaks: bool = True,
        output_format: Literal["full_text", "blocks", "lines", "detailed"] = "full_text",
    ) -> Tuple[Union[str, List[Dict]], List[Dict[str, Any]]]:
        
        word_data_list: List[Dict[str, Any]] = []
        
        # Проверка на наличие полей через HasField
        if not response_proto.HasField("objects_response") or \
           not response_proto.objects_response.HasField("text") or \
           not response_proto.objects_response.text.HasField("text_layout"):
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
                                if word.HasField("geometry") and word.geometry.HasField("bounding_box")
                                else None
                            ),
                        }
                    )

        detected_lang = response_proto.objects_response.text.content_language or "N/A"
        
        if output_format == "detailed":
            detailed_blocks = [self._parse_paragraph_detailed(p) for p in text_layout.paragraphs]
            return detailed_blocks, word_data_list

        if output_format == "lines":
            line_blocks = []
            for p in text_layout.paragraphs:
                for line in p.lines:
                    line_blocks.append(self._parse_line(line))
            return line_blocks, word_data_list

        if output_format == "blocks":
            text_blocks = [self._parse_paragraph(p) for p in text_layout.paragraphs]
            return text_blocks, word_data_list
        else:
            if preserve_line_breaks:
                full_ocr_text = "\n".join(
                    "\n".join(self._parse_paragraph(p)["lines"])
                    for p in text_layout.paragraphs
                )
            else:
                text_parts = [data["word"] + data["separator"] for data in word_data_list]
                full_ocr_text = "".join(text_parts).strip()
                full_ocr_text = " ".join(full_ocr_text.split())

            return full_ocr_text, word_data_list

    def _extract_translation_from_response(
        self, response_proto: "LensOverlayServerResponse"
    ) -> Optional[str]:
        all_translations = []
        if response_proto.HasField("objects_response"):
            for gleam in response_proto.objects_response.deep_gleams:
                if gleam.HasField("translation") and gleam.translation.status.code == TranslationDataStatusCode.SUCCESS:
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
        output_format: Literal["full_text", "blocks", "lines", "detailed"] = "full_text",
    ) -> Dict[str, Any]:
        
        async with self._semaphore:
            if isinstance(image_path, Path):
                image_path = str(image_path)

            try:
                img_bytes, width, height, original_pil_img = await prepare_image_for_api(image_path)

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
                    except Exception as e_save:
                        logger.error(f"Error saving overlay image to '{output_overlay_path}': {e_save}")

                final_result = {
                    "translated_text": translated_text,
                    "word_data": word_data,
                    "raw_response_objects": response_proto.objects_response,
                }

                if output_format == "detailed":
                    final_result["detailed_blocks"] = ocr_result
                elif output_format == "blocks":
                    final_result["text_blocks"] = ocr_result
                elif output_format == "lines":
                    final_result["line_blocks"] = ocr_result
                else:
                    final_result["ocr_text"] = ocr_result

                return final_result

            except LensException as e:
                raise
            except Exception as e:
                raise LensException(f"Unexpected error in LensAPI: {e}") from e

    async def call_raw_endpoint(
        self, 
        protobuf_payload: bytes, 
        new_session: bool = False
    ) -> bytes:
        """
        [TEST METHOD] Отправляет сырые байты Protobuf напрямую в эндпоинт Lens и возвращает ответ.
        Идеально для реверс-инжиниринга и тестов новых фич (например, aim_query или gemini_mode).
        """
        async with self._semaphore:
            if new_session:
                self.request_handler.start_new_session()

            session_uuid_for_request, _, _ = (
                self.request_handler.get_next_sequence_ids_for_request(
                    is_new_image_payload=new_session
                )
            )

            uuid_to_use = session_uuid_for_request if session_uuid_for_request else random.randint(0, (1 << 63) - 1)
            
            headers = self.request_handler._get_headers()
            
            async with httpx.AsyncClient(**self.request_handler.proxy_settings, http2=True) as client:
                response = await client.post(
                    LENS_CRUPLOAD_ENDPOINT,
                    content=protobuf_payload,
                    headers=headers,
                    timeout=self.request_handler.timeout,
                )
                response.raise_for_status()
                return await response.aread()