# src/chrome_lens_py/core/request_handler.py
import logging
from typing import Any, Dict, Optional, Tuple, Union

import httpx

from ..constants import DEFAULT_HEADERS, LENS_CRUPLOAD_ENDPOINT
from ..exceptions import LensAPIError, LensProtobufError
from ..utils.lens_betterproto import (
    LensOverlayClusterInfo,
    LensOverlayServerResponse,
    LensOverlayServerError
)

logger = logging.getLogger(__name__)

class LensRequestHandler:
    def __init__(
        self,
        api_key: str,
        proxy: Optional[Union[str, Dict[str, httpx.AsyncBaseTransport]]] = None,
        timeout: int = 60,
    ):
        self.api_key = api_key
        self.proxy_settings: Dict[str, Any] = {}
        self.timeout = timeout

        if proxy:
            if isinstance(proxy, str):
                self.proxy_settings["proxy"] = proxy
                logger.info(f"Using single proxy URL: {proxy}")
            elif isinstance(proxy, dict):
                self.proxy_settings["mounts"] = proxy
                logger.info(f"Using proxy mounts configuration: {proxy}")
            else:
                logger.warning(f"Invalid proxy type: {type(proxy)}. Proxy will not be used.")

        self.current_session_uuid: Optional[int] = None
        self.current_sequence_id: int = 0
        self.current_image_sequence_id: int = 0
        self.last_cluster_info: Optional["LensOverlayClusterInfo"] = None

    def _get_headers(self) -> dict:
        headers = DEFAULT_HEADERS.copy()
        headers["X-Goog-Api-Key"] = self.api_key
        return headers

    def start_new_session(self):
        self.current_session_uuid = None
        self.current_sequence_id = 0
        self.current_image_sequence_id = 0
        self.last_cluster_info = None
        logger.info("LensRequestHandler: New session initiated (state reset).")

    def get_next_sequence_ids_for_request(
        self, is_new_image_payload: bool
    ) -> Tuple[Optional[int], int, int]:
        self.current_sequence_id += 1
        if is_new_image_payload:
            self.current_image_sequence_id += 1

        return (
            self.current_session_uuid,
            self.current_sequence_id,
            self.current_image_sequence_id,
        )

    async def send_request(
        self, protobuf_payload: bytes, request_uuid_used: int
    ) -> "LensOverlayServerResponse":
        headers = self._get_headers()

        if self.current_session_uuid is None:
            self.current_session_uuid = request_uuid_used

        logger.info(
            "Sending request to %s (UUID: %s, SeqID: %s) with payload size: %d bytes.",
            LENS_CRUPLOAD_ENDPOINT,
            self.current_session_uuid,
            self.current_sequence_id,
            len(protobuf_payload),
        )

        response_bytes = b""
        async with httpx.AsyncClient(**self.proxy_settings, http2=True) as client:
            try:
                response = await client.post(
                    LENS_CRUPLOAD_ENDPOINT,
                    content=protobuf_payload,
                    headers=headers,
                    timeout=self.timeout,
                )
                response_bytes = await response.aread()
                response.raise_for_status()

                # Парсинг через стандартный метод FromString
                server_response_proto = LensOverlayServerResponse.FromString(response_bytes)

                if server_response_proto.HasField("error") and server_response_proto.error.error_type != 0:
                    error_msg = f"Lens API server error. Type: {server_response_proto.error.error_type}"
                    logger.error(error_msg)
                    raise LensAPIError(
                        error_msg,
                        status_code=response.status_code,
                        response_body=response_bytes.decode(errors="replace"),
                    )

                if server_response_proto.HasField("objects_response") and server_response_proto.objects_response.HasField("cluster_info"):
                    self.last_cluster_info = server_response_proto.objects_response.cluster_info
                else:
                    self.last_cluster_info = None

                return server_response_proto

            except httpx.HTTPStatusError as e_http:
                response_text_content = e_http.response.text
                raise LensAPIError(
                    f"HTTP error: {e_http.response.status_code}",
                    status_code=e_http.response.status_code,
                    response_body=response_text_content,
                ) from e_http
            except httpx.RequestError as e_req:
                raise LensAPIError(f"Network error: {e_req}") from e_req
            except Exception as e_parse:
                decoded_for_error = response_bytes.decode(errors="replace") if response_bytes else ""
                raise LensProtobufError(
                    f"Protobuf response parsing error: {e_parse}",
                    response_body=decoded_for_error,
                ) from e_parse