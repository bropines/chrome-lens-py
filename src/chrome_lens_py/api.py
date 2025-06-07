import logging
from typing import Optional, Dict, Any, List, Tuple

from PIL import ImageFont

from .core.image_processor import prepare_image_for_api, get_normalized_rect_from_box, draw_overlay_on_image
from .core.protobuf_builder import create_ocr_translate_request
from .core.request_handler import LensRequestHandler
from .utils.font_manager import get_font
from .exceptions import LensException # Убрал неиспользуемые импорты отсюда, они в других местах
from .constants import DEFAULT_OCR_LANG

try:
    from .lens_betterproto import (
        LensOverlayServerResponse, Text, DeepGleamData, TranslationDataStatusCode
    )
except ImportError:
    LensOverlayServerResponse = "LensOverlayServerResponse" #type: ignore
    Text = "Text" #type: ignore
    DeepGleamData = "DeepGleamData" #type: ignore
    TranslationDataStatusCode = "TranslationDataStatusCode" #type: ignore


logger = logging.getLogger(__name__)

class LensAPI:
    def __init__(
        self,
        api_key: str,
        client_region: Optional[str] = None,
        client_time_zone: Optional[str] = None,
        proxy: Optional[str] = None,
        timeout: int = 60,
        font_path: Optional[str] = None,
        font_size: Optional[int] = None
    ):
        self.request_handler = LensRequestHandler(api_key=api_key, proxy=proxy, timeout=timeout)
        self.client_region = client_region
        self.client_time_zone = client_time_zone
        self.font_path = font_path
        self.font_size = font_size
        self._font_object: Optional[ImageFont.FreeTypeFont] = None

    def _get_font(self) -> ImageFont.FreeTypeFont:
        if not self._font_object:
            self._font_object = get_font(font_path_override=self.font_path, font_size_override=self.font_size)
        return self._font_object

    def _extract_ocr_data_from_response(self, response_proto: LensOverlayServerResponse) -> Tuple[str, List[Tuple[float, float, float, float]]]:
        full_ocr_text_parts = []
        word_boxes_norm = []

        if response_proto.objects_response and \
           response_proto.objects_response.text and \
           response_proto.objects_response.text.text_layout:
            text_layout = response_proto.objects_response.text.text_layout
            for paragraph in text_layout.paragraphs:
                for line in paragraph.lines:
                    for word in line.words:
                        full_ocr_text_parts.append(word.plain_text)
                        if word.geometry and word.geometry.bounding_box:
                            norm_rect = get_normalized_rect_from_box(word.geometry.bounding_box)
                            if norm_rect:
                                word_boxes_norm.append(norm_rect)
                        if word.text_separator is not None:
                            full_ocr_text_parts.append(word.text_separator)

        full_ocr_text = "".join(full_ocr_text_parts).strip()
        detected_lang = "N/A"
        if response_proto.objects_response and \
           response_proto.objects_response.text and \
           response_proto.objects_response.text.content_language:
            detected_lang = response_proto.objects_response.text.content_language
        
        logger.info(f"Extracted OCR text (first 100 chars): '{full_ocr_text[:100]}...'. Detected language: {detected_lang}")
        logger.info(f"Extracted {len(word_boxes_norm)} word bounding boxes.")
        return full_ocr_text, word_boxes_norm

    def _extract_translation_from_response(self, response_proto: LensOverlayServerResponse) -> Optional[str]:
        all_translations: List[str] = [] # Список для сбора всех частей перевода
        any_translation_successful = False

        if response_proto.objects_response and response_proto.objects_response.deep_gleams:
            for i, gleam in enumerate(response_proto.objects_response.deep_gleams):
                if gleam.translation:
                    if gleam.translation.status.code == TranslationDataStatusCode.SUCCESS:
                        translated_text_part = gleam.translation.translation
                        if translated_text_part: # Добавляем, только если текст не пустой
                            all_translations.append(translated_text_part)
                            any_translation_successful = True
                            src_lang = gleam.translation.source_language
                            tgt_lang = gleam.translation.target_language
                            logger.debug(f"Gleam #{i+1}: Extracted translation part ({src_lang} -> {tgt_lang}): '{translated_text_part[:100]}...'")
                    else:
                        logger.warning(
                            f"Gleam #{i+1}: Translation found but status not SUCCESS. Status: {gleam.translation.status.code}, "
                            f"Source: {gleam.translation.source_language}, Target: {gleam.translation.target_language}"
                        )
        
        if not any_translation_successful:
            logger.info("No successful translation data found in any deep gleams.")
            return None
        
        # Объединяем все части перевода. Можно использовать '\n' или ' ' в зависимости от того,
        # как они должны быть представлены. Для простоты пока объединим через пробел.
        # Если структура подразумевает, что каждый gleam.translation.translation это отдельная строка, то '\n'.
        # Судя по выводу твоего main2.py, это отдельные смысловые блоки, так что пробел или новая строка.
        # Давай попробуем новую строку, это часто лучше для разных блоков.
        final_translated_text = "\n".join(all_translations).strip()
        if final_translated_text:
            logger.info(f"Consolidated translated text (first 100 chars): '{final_translated_text[:100]}...'")
            return final_translated_text
        else:
            logger.info("Consolidated translated text is empty after joining parts.")
            return None


    async def process_image(
        self,
        image_path: str,
        ocr_language: Optional[str] = DEFAULT_OCR_LANG,
        target_translation_language: Optional[str] = None,
        source_translation_language: Optional[str] = None,
        output_overlay_path: Optional[str] = None,
        new_session: bool = True
    ) -> Dict[str, Any]:
        logger.info(f"Processing image: {image_path}")
        try:
            img_bytes, width, height, original_pil_img = prepare_image_for_api(image_path)

            if new_session:
                self.request_handler.start_new_session()
            
            session_uuid_for_request, seq_id, img_seq_id = self.request_handler.get_next_sequence_ids_for_request(
                is_new_image_payload=new_session 
            )
            routing_info_to_send = self.request_handler.last_cluster_info.routing_info if self.request_handler.last_cluster_info else None
            
            effective_ocr_lang = ocr_language if ocr_language is not None else DEFAULT_OCR_LANG

            proto_payload, uuid_for_this_request = create_ocr_translate_request(
                image_bytes=img_bytes,
                width=width,
                height=height,
                ocr_language=effective_ocr_lang,
                target_translation_language=target_translation_language,
                source_translation_language=source_translation_language,
                client_region=self.client_region,
                client_time_zone=self.client_time_zone,
                session_uuid=session_uuid_for_request,
                sequence_id=seq_id,
                image_sequence_id=img_seq_id,
                routing_info=routing_info_to_send
            )

            response_proto = await self.request_handler.send_request(
                proto_payload, 
                request_uuid_used=uuid_for_this_request
            )
            
            ocr_text, word_boxes_norm = self._extract_ocr_data_from_response(response_proto)
            translated_text = None
            if target_translation_language:
                translated_text = self._extract_translation_from_response(response_proto)

            if output_overlay_path and translated_text: # Накладываем, только если есть переведенный текст
                font_to_use = self._get_font()
                overlay_image = draw_overlay_on_image(
                    original_image=original_pil_img,
                    ocr_boxes_norm=word_boxes_norm, # Передаем OCR boxes для закрашивания
                    translated_text=translated_text,
                    font=font_to_use
                )
                try:
                    overlay_image.save(output_overlay_path)
                    logger.info(f"Image with overlay saved to: {output_overlay_path}")
                except Exception as e_save:
                    logger.error(f"Error saving overlay image to '{output_overlay_path}': {e_save}")
            elif output_overlay_path and not translated_text: # Если путь указан, но текста нет
                logger.warning(f"Overlay output path '{output_overlay_path}' specified, but no translated text available to overlay. Original image (or OCR-filled) will not be saved by this logic.")
                # Можно добавить логику сохранения изображения с закрашенным OCR, если это нужно, даже без перевода


            return {
                "ocr_text": ocr_text,
                "translated_text": translated_text,
                "word_coordinates_normalized": word_boxes_norm,
                "raw_response_objects": response_proto.objects_response
            }

        except LensException as e:
            logger.error(f"LensAPI processing error: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Unexpected error in LensAPI: {e}", exc_info=True)
            raise LensException(f"Непредвиденная ошибка в LensAPI: {e}") from e