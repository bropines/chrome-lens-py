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
    LENS_CRUPLOAD_ENDPOINT,
)
from .core.image_processor import (
    crop_region,
    draw_overlay_on_image,
    get_word_geometry_data,
    prepare_image_for_api,
)
from .core.protobuf_builder import create_ocr_translate_request, create_region_request
from .core.request_handler import LensRequestHandler
from .core.text_renderer import render_translation_overlay
from .exceptions import LensException
from .utils.font_manager import FontType, get_default_system_font_path, get_font
from .utils.lens_betterproto import (
    Alignment,
    BackgroundImageDataFileFormat,
    LensOverlayServerResponse,
    Polygon,
    TextLayoutLine,
    TextLayoutParagraph,
    TextLayoutWord,
    TextLayoutWordType,
    TranslationDataStatusCode,
    WritingDirection,
)

logger = logging.getLogger(__name__)

# Sentinel so a font lookup that legitimately returns None is cached, not retried.
_UNRESOLVED = object()


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
        trust_env: bool = True,
    ):
        self.request_handler = LensRequestHandler(
            api_key=api_key,
            proxy=proxy,
            timeout=timeout,
            trust_env=trust_env,
            max_connections=max(max_concurrent * 2, 8),
        )
        self.client_region = client_region
        self.client_time_zone = client_time_zone
        self.font_path = font_path
        self.font_size = font_size
        self._font_object: Optional[FontType] = None
        self._font_path_resolved: Any = _UNRESOLVED
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def aclose(self) -> None:
        """Release the pooled HTTP connections."""
        await self.request_handler.aclose()

    async def __aenter__(self) -> "LensAPI":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    def _get_font(self) -> FontType:
        if not self._font_object:
            self._font_object = get_font(
                font_path_override=self.font_path, font_size_override=self.font_size
            )
        return self._font_object

    def _get_font_path(self) -> Optional[str]:
        """The Chromium-style renderer needs a path, not a sized font object.

        It re-instantiates the face at many sizes while searching for the one
        that fits each line.
        """
        if self._font_path_resolved is _UNRESOLVED:
            self._font_path_resolved = self.font_path or get_default_system_font_path()
        return self._font_path_resolved

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
        parsed: Dict[str, Any] = {
            "text": word.plain_text,
            "separator": word.text_separator,
            "geometry": geometry_data,
        }
        # The server decides on its own whether a word is a formula; there is no
        # request flag for it, so these two fields simply arrive populated.
        if word.type == TextLayoutWordType.FORMULA:
            parsed["type"] = "FORMULA"
            if word.formula_metadata.latex:
                parsed["latex"] = word.formula_metadata.latex
        return parsed

    def _parse_polygon(self, polygon: "Polygon") -> Dict[str, Any]:
        return {
            "vertices": [(v.x, v.y) for v in polygon.vertex],
            "coordinate_type": {1: "NORMALIZED", 2: "IMAGE"}.get(
                polygon.coordinate_type, "UNSPECIFIED"
            ),
            "ordering": {1: "CLOCKWISE", 2: "COUNTER_CLOCKWISE"}.get(
                polygon.vertex_ordering, "UNSPECIFIED"
            ),
        }

    def _extract_objects_from_response(
        self, response_proto: "LensOverlayServerResponse"
    ) -> List[Dict[str, Any]]:
        """Detected objects, with their segmentation masks when present.

        Chromium hides any object whose `select_on_tap` is false, so it renders
        strictly fewer than the server sends. We return all of them and expose
        the flag instead.
        """
        if not response_proto.HasField("objects_response"):
            return []

        objects: List[Dict[str, Any]] = []
        for obj in response_proto.objects_response.overlay_objects:
            geometry = obj.geometry
            objects.append(
                {
                    "id": obj.id,
                    "geometry": (
                        get_word_geometry_data(geometry.bounding_box)
                        if geometry.HasField("bounding_box")
                        else None
                    ),
                    "segmentation_polygons": [
                        self._parse_polygon(p) for p in geometry.segmentation_polygon
                    ],
                    "select_on_tap": obj.interaction_properties.select_on_tap,
                    "is_fulfilled": obj.is_fulfilled,
                    "render_type": (
                        "GLEAM"
                        if obj.rendering_metadata.render_type == 1
                        else "DEFAULT"
                    ),
                }
            )
        return objects

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

    def _parse_paragraph_detailed(
        self, paragraph: "TextLayoutParagraph"
    ) -> Dict[str, Any]:
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
        output_format: Literal[
            "full_text", "blocks", "lines", "detailed"
        ] = "full_text",
    ) -> Tuple[Union[str, List[Dict]], List[Dict[str, Any]]]:

        word_data_list: List[Dict[str, Any]] = []

        # Проверка на наличие полей через HasField
        if (
            not response_proto.HasField("objects_response")
            or not response_proto.objects_response.HasField("text")
            or not response_proto.objects_response.text.HasField("text_layout")
        ):
            return ("", []) if output_format == "full_text" else ([], [])

        text_layout = response_proto.objects_response.text.text_layout

        for paragraph in text_layout.paragraphs:
            for line in paragraph.lines:
                for word in line.words:
                    entry = {
                        "word": word.plain_text,
                        "separator": word.text_separator,
                        "geometry": (
                            get_word_geometry_data(word.geometry.bounding_box)
                            if word.HasField("geometry")
                            and word.geometry.HasField("bounding_box")
                            else None
                        ),
                    }
                    if word.type == TextLayoutWordType.FORMULA:
                        entry["type"] = "FORMULA"
                        if word.formula_metadata.latex:
                            entry["latex"] = word.formula_metadata.latex
                    word_data_list.append(entry)

        detected_lang = response_proto.objects_response.text.content_language or "N/A"
        logger.debug(f"Detected language: {detected_lang}")

        if output_format == "detailed":
            detailed_blocks = [
                self._parse_paragraph_detailed(p) for p in text_layout.paragraphs
            ]
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
                text_parts = [
                    data["word"] + data["separator"] for data in word_data_list
                ]
                full_ocr_text = "".join(text_parts).strip()
                full_ocr_text = " ".join(full_ocr_text.split())

            return full_ocr_text, word_data_list

    def _extract_translation_from_response(
        self, response_proto: "LensOverlayServerResponse"
    ) -> Optional[str]:
        all_translations = []
        if response_proto.HasField("objects_response"):
            for gleam in response_proto.objects_response.deep_gleams:
                if (
                    gleam.HasField("translation")
                    and gleam.translation.status.code
                    == TranslationDataStatusCode.SUCCESS
                ):
                    if gleam.translation.translation:
                        all_translations.append(gleam.translation.translation)
        return "\n".join(all_translations).strip() or None

    def _extract_translation_render_data(
        self, response_proto: "LensOverlayServerResponse"
    ) -> List[Dict[str, Any]]:
        """Everything needed to repaint the translation yourself.

        The same data `core.text_renderer` consumes, surfaced so callers can
        render in a browser, a game overlay, or anything else. Note that the
        server has only ever been observed emitting WEBP_RGBA backgrounds, in
        which case `text_mask` comes back empty.
        """
        if not response_proto.HasField("objects_response"):
            return []

        paragraphs = response_proto.objects_response.text.text_layout.paragraphs
        blocks: List[Dict[str, Any]] = []

        for index, gleam in enumerate(response_proto.objects_response.deep_gleams):
            if not gleam.HasField("translation"):
                continue
            data = gleam.translation
            if data.status.code != TranslationDataStatusCode.SUCCESS:
                continue

            source_lines = paragraphs[index].lines if index < len(paragraphs) else []
            lines = []
            for line_index, line in enumerate(data.line):
                geometry = (
                    get_word_geometry_data(
                        source_lines[line_index].geometry.bounding_box
                    )
                    if line_index < len(source_lines)
                    else None
                )
                entry: Dict[str, Any] = {
                    # Character ranges index the paragraph translation by UTF-16
                    # code unit, matching icu::UnicodeString.
                    "range": (line.start, line.end),
                    "words": [(w.start, w.end) for w in line.word],
                    "text_color_argb": line.style.text_color,
                    "background_color_argb": line.style.background_primary_color,
                    # Geometry is borrowed from the detected line: the server
                    # sends none for translated text.
                    "geometry": geometry,
                    "background_image": None,
                }
                if line.HasField("background_image_data"):
                    bgd = line.background_image_data
                    entry["background_image"] = {
                        "bytes": bgd.background_image,
                        "width": bgd.image_width,
                        "height": bgd.image_height,
                        "vertical_padding": bgd.vertical_padding,
                        "horizontal_padding": bgd.horizontal_padding,
                        "file_format": BackgroundImageDataFileFormat.Name(
                            bgd.file_format
                        ),
                        "text_mask": bgd.text_mask or None,
                    }
                lines.append(entry)

            blocks.append(
                {
                    "translation": data.translation,
                    "source_language": data.source_language,
                    "target_language": data.target_language,
                    "writing_direction": WritingDirection.Name(data.writing_direction),
                    "alignment": Alignment.Name(data.alignment),
                    "justified": data.justified,
                    "lines": lines,
                }
            )
        return blocks

    async def process_image(
        self,
        image_path: Any,
        ocr_language: Optional[str] = None,
        target_translation_language: Optional[str] = None,
        source_translation_language: Optional[str] = None,
        output_overlay_path: Optional[str] = None,
        new_session: bool = True,
        ocr_preserve_line_breaks: bool = True,
        output_format: Literal[
            "full_text", "blocks", "lines", "detailed"
        ] = "full_text",
        overlay_mode: Literal["chromium", "legacy"] = "chromium",
        vertical_text: Literal["keep", "auto", "horizontal"] = "auto",
        erase_mode: Literal["patch", "hull"] = "patch",
        hull_padding: float = 0.45,
        outline_scale: float = 1.0,
        min_readable_px: float = 0.0,
        text_align: Literal["auto", "left", "center", "right"] = "auto",
        manga_mode: bool = False,
        manga_box_growth: float = 1.45,
        include_raw_response: bool = False,
    ) -> Dict[str, Any]:

        async with self._semaphore:
            if isinstance(image_path, Path):
                image_path = str(image_path)

            try:
                client = await self.request_handler.get_client()
                img_bytes, width, height, original_pil_img = (
                    await prepare_image_for_api(
                        image_path,
                        client=client,
                        keep_original=bool(output_overlay_path),
                    )
                )

                # A fresh session per call, so concurrent workers no longer
                # clobber each other's sequence counters and routing info.
                session = (
                    self.request_handler.new_session()
                    if new_session
                    else self.request_handler.default_session
                )
                session_uuid_for_request, seq_id, img_seq_id = await session.next_ids(
                    is_new_image_payload=new_session
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
                        session.cluster_info.routing_info
                        if session.cluster_info
                        else None
                    ),
                )

                response_proto = await self.request_handler.send_request(
                    proto_payload,
                    request_uuid_used=uuid_for_this_request,
                    session=session,
                )

                ocr_result, word_data = self._extract_ocr_data_from_response(
                    response_proto, ocr_preserve_line_breaks, output_format
                )

                translated_text = (
                    self._extract_translation_from_response(response_proto)
                    if target_translation_language
                    else None
                )

                if output_overlay_path and translated_text and original_pil_img:
                    if overlay_mode == "chromium":
                        overlay_image = render_translation_overlay(
                            original_pil_img,
                            response_proto.objects_response,
                            font_path=self._get_font_path(),
                            vertical_text=vertical_text,
                            erase_mode=erase_mode,
                            hull_padding=hull_padding,
                            outline_scale=outline_scale,
                            min_readable_px=min_readable_px,
                            text_align=text_align,
                            manga_mode=manga_mode,
                            manga_box_growth=manga_box_growth,
                        )
                    else:
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
                        if overlay_image.mode == "RGBA" and str(
                            output_overlay_path
                        ).lower().endswith((".jpg", ".jpeg")):
                            overlay_image = overlay_image.convert("RGB")
                        overlay_image.save(output_overlay_path)
                    except Exception as e_save:
                        logger.error(
                            "Error saving overlay image to '%s': %s",
                            output_overlay_path,
                            e_save,
                        )

                final_result = {
                    "translated_text": translated_text,
                    "word_data": word_data,
                    "detected_language": (
                        response_proto.objects_response.text.content_language or None
                    ),
                    "objects": self._extract_objects_from_response(response_proto),
                    "translation_render_data": (
                        self._extract_translation_render_data(response_proto)
                        if target_translation_language
                        else []
                    ),
                }
                if include_raw_response:
                    # Opt-in: this is a live protobuf object, not JSON-safe, and
                    # leaking it by default made the public result awkward to
                    # serialize or log.
                    final_result["raw_response_objects"] = (
                        response_proto.objects_response
                    )

                if output_format == "detailed":
                    final_result["detailed_blocks"] = ocr_result
                elif output_format == "blocks":
                    final_result["text_blocks"] = ocr_result
                elif output_format == "lines":
                    final_result["line_blocks"] = ocr_result
                else:
                    final_result["ocr_text"] = ocr_result

                return final_result

            except LensException:
                raise
            except Exception as e:
                raise LensException(f"Unexpected error in LensAPI: {e}") from e

    async def process_region(
        self,
        image_path: Any,
        region: Tuple[float, float, float, float],
        ocr_language: Optional[str] = None,
        text_query: Optional[str] = None,
        ocr_preserve_line_breaks: bool = True,
    ) -> Dict[str, Any]:
        """Re-read one region of an image at native resolution.

        Runs the full-image pass first (the server will not accept a follow-up
        without a session), then sends just the cropped pixels. Because the crop
        is not competing with the rest of the page for the downscale budget,
        small text comes back markedly better than in the full-image result.

        `region` is (center_x, center_y, width, height), normalized 0..1 against
        the full image. Returned geometry is rescaled back to full-image
        coordinates, so it is directly comparable with process_image output.
        """
        async with self._semaphore:
            if isinstance(image_path, Path):
                image_path = str(image_path)

            try:
                client = await self.request_handler.get_client()
                _, _, _, original = await prepare_image_for_api(
                    image_path, client=client, keep_original=True
                )
                if original is None:
                    raise LensException("Could not load the source image.")

                # 1. Full-image pass, purely to establish the session.
                session = self.request_handler.new_session()
                uuid_seed, seq_id, img_seq_id = await session.next_ids(True)
                full_bytes, full_w, full_h, _ = await prepare_image_for_api(
                    original, client=client, keep_original=False
                )
                payload, uuid_used = create_ocr_translate_request(
                    image_bytes=full_bytes,
                    width=full_w,
                    height=full_h,
                    ocr_language=ocr_language or DEFAULT_OCR_LANG,
                    client_region=self.client_region or DEFAULT_CLIENT_REGION,
                    client_time_zone=self.client_time_zone or DEFAULT_CLIENT_TIME_ZONE,
                    session_uuid=uuid_seed,
                    sequence_id=seq_id,
                    image_sequence_id=img_seq_id,
                )
                await self.request_handler.send_request(
                    payload, request_uuid_used=uuid_used, session=session
                )

                # 2. Region pass. sequence_id advances; image_sequence_id does not.
                crop_bytes, crop_w, crop_h = crop_region(original, region)
                _, seq_id, img_seq_id = await session.next_ids(False)
                region_payload = create_region_request(
                    crop_bytes=crop_bytes,
                    region=region,
                    parent_width=original.width,
                    parent_height=original.height,
                    crop_width=crop_w,
                    ocr_language=ocr_language or DEFAULT_OCR_LANG,
                    session_uuid=session.uuid,
                    sequence_id=seq_id,
                    image_sequence_id=img_seq_id,
                    client_region=self.client_region or DEFAULT_CLIENT_REGION,
                    client_time_zone=self.client_time_zone or DEFAULT_CLIENT_TIME_ZONE,
                    routing_info=(
                        session.cluster_info.routing_info
                        if session.cluster_info
                        else None
                    ),
                    text_query=text_query,
                )
                response = await self.request_handler.send_interaction(
                    region_payload, session=session
                )

                text = response.interaction_response.text
                lines: List[Dict[str, Any]] = []
                words: List[Dict[str, Any]] = []
                for paragraph in text.text_layout.paragraphs:
                    for line in paragraph.lines:
                        # No rescaling: because the request carries zoomed_crop
                        # (parent dimensions plus the crop box), the server
                        # returns geometry already normalized to the full image.
                        # Verified against the full-image pass on 39 matched
                        # words, agreeing to under 2px on a 2400px-wide page.
                        parsed = self._parse_line_detailed(line)
                        words.extend(parsed["words"])
                        lines.append(parsed)

                joiner = "\n" if ocr_preserve_line_breaks else " "
                return {
                    "ocr_text": joiner.join(ln["text"] for ln in lines),
                    "line_blocks": lines,
                    "word_data": words,
                    "detected_language": text.content_language or None,
                    "region": region,
                    "crop_size": (crop_w, crop_h),
                    "encoded_response": response.interaction_response.encoded_response,
                }

            except LensException:
                raise
            except Exception as e:
                raise LensException(f"Unexpected error in process_region: {e}") from e

    async def call_raw_endpoint(
        self, protobuf_payload: bytes, new_session: bool = False
    ) -> bytes:
        """
        [TEST METHOD] Отправляет сырые байты Protobuf напрямую в эндпоинт Lens и возвращает ответ.
        Идеально для реверс-инжиниринга и тестов новых фич (например, aim_query или gemini_mode).
        """
        async with self._semaphore:
            if new_session:
                self.request_handler.start_new_session()

            response = await self.request_handler.post_raw(protobuf_payload)
            response.raise_for_status()
            return await response.aread()
