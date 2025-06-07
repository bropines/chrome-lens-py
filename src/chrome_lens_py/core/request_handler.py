import logging
import httpx
from typing import Optional, Tuple # Добавил Tuple

from ..constants import LENS_CRUPLOAD_ENDPOINT, DEFAULT_HEADERS
from ..exceptions import LensAPIError, LensProtobufError

try:
    from ..lens_betterproto import LensOverlayServerResponse, LensOverlayClusterInfo, LensOverlayRoutingInfo
except ImportError:
    LensOverlayServerResponse = "LensOverlayServerResponse" # type: ignore
    LensOverlayClusterInfo = "LensOverlayClusterInfo" # type: ignore
    LensOverlayRoutingInfo = "LensOverlayRoutingInfo" #type: ignore


logger = logging.getLogger(__name__)

class LensRequestHandler:
    def __init__(self, api_key: str, proxy: Optional[str] = None, timeout: int = 60):
        self.api_key = api_key
        self.proxy_config = {"proxy": proxy} if proxy else {}
        self.timeout = timeout
        
        # Состояние текущей "сессии" RequestHandler'а
        self.current_session_uuid: Optional[int] = None
        self.current_sequence_id: int = 0
        self.current_image_sequence_id: int = 0 # Считает только запросы с НОВЫМ изображением
        self.last_cluster_info: Optional[LensOverlayClusterInfo] = None

    def _get_headers(self) -> dict:
        headers = DEFAULT_HEADERS.copy()
        headers["X-Goog-Api-Key"] = self.api_key
        return headers

    def start_new_session(self):
        """Сбрасывает состояние сессии для начала новой серии запросов."""
        self.current_session_uuid = None # protobuf_builder сгенерирует новый
        self.current_sequence_id = 0
        self.current_image_sequence_id = 0
        self.last_cluster_info = None
        logger.info("LensRequestHandler: New session initiated (state reset).")

    def get_next_sequence_ids_for_request(self, is_new_image_payload: bool) -> Tuple[Optional[int], int, int]:
        """
        Возвращает UUID для текущей сессии и инкрементированные sequence_id / image_sequence_id.
        UUID будет None, если это первый запрос в новой сессии (будет сгенерирован в protobuf_builder).
        """
        self.current_sequence_id += 1
        if is_new_image_payload:
            self.current_image_sequence_id += 1
        
        # Если current_session_uuid еще не установлен (первый запрос после start_new_session),
        # то он останется None, и protobuf_builder сгенерирует новый.
        # Если он уже есть, то используем его.
        logger.debug(
            f"RequestHandler: Providing IDs for request: "
            f"SessionUUID (current): {self.current_session_uuid}, "
            f"Next SeqID: {self.current_sequence_id}, "
            f"Next ImgSeqID: {self.current_image_sequence_id} (is_new_image: {is_new_image_payload})"
        )
        return self.current_session_uuid, self.current_sequence_id, self.current_image_sequence_id

    async def send_request(
        self, 
        protobuf_payload: bytes,
        request_uuid_used: int # UUID, который был фактически использован (или сгенерирован) для этого запроса
    ) -> LensOverlayServerResponse:
        """
        Асинхронно отправляет Protobuf запрос и возвращает распарсенный ответ.
        Обновляет current_session_uuid, если он был None (т.е. сгенерирован для этого запроса).
        """
        headers = self._get_headers()
        
        # Если current_session_uuid был None до этого запроса, значит он был сгенерирован
        # в protobuf_builder и передан сюда через request_uuid_used. Устанавливаем его.
        if self.current_session_uuid is None:
            self.current_session_uuid = request_uuid_used
            logger.info(f"RequestHandler: Session UUID initialized by this request: {self.current_session_uuid}")

        logger.info(f"Sending request to {LENS_CRUPLOAD_ENDPOINT} (UUID: {self.current_session_uuid}, SeqID: {self.current_sequence_id}) with payload size: {len(protobuf_payload)} bytes.")
        
        async with httpx.AsyncClient(**self.proxy_config, http2=True) as client:
            try:
                response = await client.post(
                    LENS_CRUPLOAD_ENDPOINT,
                    content=protobuf_payload,
                    headers=headers,
                    timeout=self.timeout
                )
                logger.debug(f"Response status: {response.status_code}")
                response.raise_for_status()

                response_bytes = await response.aread()
                logger.debug(f"Response content length: {len(response_bytes)} bytes.")

                server_response_proto = LensOverlayServerResponse().parse(response_bytes)

                if server_response_proto.error and server_response_proto.error.error_type != 0:
                    error_msg = f"Lens API server error. Type: {server_response_proto.error.error_type}"
                    logger.error(error_msg)
                    raise LensAPIError(error_msg, status_code=response.status_code, response_body="Protobuf error indicated by server.")

                if server_response_proto.objects_response and server_response_proto.objects_response.cluster_info:
                    self.last_cluster_info = server_response_proto.objects_response.cluster_info
                    logger.debug(
                        f"RequestHandler: Updated last_cluster_info. ServerSessionID: {self.last_cluster_info.server_session_id}, "
                        f"RoutingInfo available: {bool(self.last_cluster_info.routing_info)}"
                    )
                else:
                    # Если cluster_info не пришел, сбрасываем его, чтобы не использовать устаревший
                    self.last_cluster_info = None
                    logger.debug("RequestHandler: No cluster_info in response or no objects_response.")


                return server_response_proto

            except httpx.HTTPStatusError as e_http:
                response_text = await e_http.response.atext()
                logger.error(f"HTTP error: {e_http.response.status_code} - {response_text[:500]}", exc_info=True)
                raise LensAPIError(
                    f"HTTP ошибка: {e_http.response.status_code}",
                    status_code=e_http.response.status_code,
                    response_body=response_text
                ) from e_http
            except httpx.RequestError as e_req:
                logger.error(f"Request error: {e_req}", exc_info=True)
                raise LensAPIError(f"Ошибка сети или запроса: {e_req}") from e_req
            except (LensProtobufError, ValueError) as e_parse:
                logger.error(f"Error parsing Protobuf response: {e_parse}", exc_info=True)
                try: raw_response = response_bytes
                except NameError: raw_response = "N/A (error before response_bytes assignment)"
                raise LensProtobufError(f"Ошибка парсинга Protobuf ответа: {e_parse}", response_body=raw_response)
            except Exception as e_gen:
                logger.error(f"Unexpected error during request: {e_gen}", exc_info=True)
                raise LensAPIError(f"Непредвиденная ошибка при выполнении запроса: {e_gen}")