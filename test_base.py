import asyncio
import logging
from chrome_lens_py import LensAPI
from chrome_lens_py.core.image_processor import prepare_image_for_api
from chrome_lens_py.core.protobuf_builder import create_ocr_translate_request

# Настраиваем логирование, чтобы видеть всё, что происходит под капотом
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# Импортируем классы напрямую из нашего коннектора
from chrome_lens_py.utils.lens_betterproto import (
    LensOverlayServerRequest,
    Platform,
    Surface,
    LensOverlayServerResponse,
    LensOverlayInteractionRequestMetadataType,
    QueryPayload,
    ModelMode,
    RequestType
)

async def main():
    api = LensAPI() # Убрали logging_level отсюда
    image_url = "https://avatars.mds.yandex.net/get-kinopoisk-image/4303601/9e44389e-0205-433d-9bca-d90a8bea0a32/1200x630"
    
    print("\n==================================================")
    print("🚀 СТАРТ МЕГА-ТЕСТА LENS API 🚀")
    print("==================================================\n")

    # --- ТЕСТ 1: Инициализация сессии (Upload) ---
    print("[ТЕСТ 1] Загрузка картинки и получение Session UUID...")
    try:
        img_bytes, width, height, _ = await prepare_image_for_api(image_url)
        
        # Используем встроенный билдер для надежности первого запроса
        proto_payload, uuid_used = create_ocr_translate_request(
            image_bytes=img_bytes,
            width=width,
            height=height,
            ocr_language="ru",
            sequence_id=1,
            image_sequence_id=1
        )
        
        raw_response = await api.call_raw_endpoint(proto_payload, new_session=True)
        response_1 = LensOverlayServerResponse.FromString(raw_response)
        
        print(f"✅ Успех! Сессия открыта. UUID: {uuid_used}")
        if response_1.HasField("objects_response") and response_1.objects_response.HasField("cluster_info"):
            print(f"✅ Cluster Info получен: {response_1.objects_response.cluster_info.server_session_id}")
        else:
            print("⚠️ Cluster Info не найден (но это норм).")
            
    except Exception as e:
        print(f"❌ Провал Теста 1: {e}")
        return # Без сессии дальше идти нет смысла


    # --- ТЕСТ 2: Текстовый запрос (Interaction Request) ---
    print("\n[ТЕСТ 2] Эмуляция текстового поиска Lens (Кто такой Олег Вебер?)...")
    try:
        req_2 = LensOverlayServerRequest()
        
        # Настраиваем контекст для 2-го запроса в той же сессии
        req_ctx = req_2.interaction_request.request_context
        req_ctx.request_id.uuid = uuid_used
        req_ctx.request_id.sequence_id = 2 # Увеличиваем sequence_id!
        req_ctx.client_context.platform = Platform.PLATFORM_WEB
        req_ctx.client_context.surface = Surface.SURFACE_CHROMIUM
        
        # Собираем Interaction Request
        interact_meta = req_2.interaction_request.interaction_request_metadata
        interact_meta.type = LensOverlayInteractionRequestMetadataType.CONTEXTUAL_SEARCH_QUERY
        interact_meta.query_metadata.text_query.query = "Кто такой Олег Вебер?"
        
        raw_payload_2 = req_2.SerializeToString()
        raw_response_2 = await api.call_raw_endpoint(raw_payload_2, new_session=False)
        response_2 = LensOverlayServerResponse.FromString(raw_response_2)
        
        print(f"✅ Ответ получен ({len(raw_response_2)} байт).")
        if response_2.HasField("interaction_response"):
            print("✅ Сервер вернул interaction_response! Похоже, текстовый поиск работает.")
            # Обычно тут возвращается encoded_response (HTML или JSON от гугла)
            print(f"Сырой ответ (первые 100 символов): {response_2.interaction_response.encoded_response[:100]}...")
        else:
            print("⚠️ Сервер не вернул interaction_response. Возможно, не хватает данных региона (ImageCrop).")
            if response_2.HasField("error"):
                 print(f"Код ошибки сервера: {response_2.error.error_type}")
                 
    except Exception as e:
        print(f"❌ Провал Теста 2: {e}")


    # --- ТЕСТ 3: Наглый запрос к Gemini (Payload / Aim Query) ---
    print("\n[ТЕСТ 3] Попытка прокинуть QueryPayload для Gemini Pro...")
    try:
        req_3 = LensOverlayServerRequest()
        req_ctx = req_3.objects_request.request_context
        req_ctx.request_id.uuid = uuid_used
        req_ctx.request_id.sequence_id = 3
        req_ctx.client_context.platform = Platform.PLATFORM_WEB
        req_ctx.client_context.surface = Surface.SURFACE_CHROMIUM
        
        # Собираем AIM Query
        gemini_query = QueryPayload()
        gemini_query.query_text = "Summarize this image"
        gemini_query.model_mode = ModelMode.MODEL_MODE_GEMINI_PRO
        
        # Пытаемся засунуть его в payload объектов
        payload_obj = req_3.objects_request.payload
        payload_obj.request_type = RequestType.REQUEST_TYPE_DEFAULT
        payload_obj.content_type = "application/x-protobuf"
        payload_obj.content_data = gemini_query.SerializeToString()
        
        raw_payload_3 = req_3.SerializeToString()
        raw_response_3 = await api.call_raw_endpoint(raw_payload_3, new_session=False)
        response_3 = LensOverlayServerResponse.FromString(raw_response_3)
        
        print(f"✅ Запрос ушел! Ответ ({len(raw_response_3)} байт).")
        if response_3.HasField("error"):
            print(f"⚠️ Гугл ругается на формат. Код ошибки сервера: {response_3.error.error_type}")
            print("Скорее всего, QueryPayload нужно слать на другой эндпоинт или оборачивать иначе.")
        else:
            print("✅ Ошибки нет! Сервер схавал payload Gemini. Надо ковырять objects_response.")
            
    except Exception as e:
        print(f"❌ Провал Теста 3: {e}")

    print("\n==================================================")
    print("🏁 ТЕСТЫ ЗАВЕРШЕНЫ 🏁")
    print("==================================================\n")

if __name__ == "__main__":
    asyncio.run(main())