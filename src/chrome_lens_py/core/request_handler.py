import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

import httpx

from ..constants import DEFAULT_HEADERS, LENS_CRUPLOAD_ENDPOINT
from ..exceptions import LensAPIError, LensProtobufError

if TYPE_CHECKING:
    from ..utils.lens_betterproto import (
        LensOverlayClusterInfo,
        LensOverlayRoutingInfo,
        LensOverlayServerResponse,
    )
else:
    from ..utils.lens_betterproto import (
        LensOverlayClusterInfo,
        LensOverlayRoutingInfo,
        LensOverlayServerResponse,
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
                logger.warning(
                    f"Invalid proxy type: {type(proxy)}. Proxy will not be used."
                )

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

        logger.debug(
            f"RequestHandler: Providing IDs for request: "
            f"SessionUUID (current): {self.current_session_uuid}, "
            f"Next SeqID: {self.current_sequence_id}, "
            f"Next ImgSeqID: {self.current_image_sequence_id} (is_new_image: {is_new_image_payload})"
        )
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
                f"RequestHandler: Session UUID initialized by this request: {self.current_session_uuid}"
            )

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
                logger.debug(f"Response status: {response.status_code}")
                response_bytes = await response.aread()
                response.raise_for_status()

                logger.debug(f"Response content length: {len(response_bytes)} bytes.")

                server_response_proto = LensOverlayServerResponse().parse(
                    response_bytes
                )

                if (
                    server_response_proto.error
                    and server_response_proto.error.error_type != 0
                ):
                    error_msg = f"Lens API server error. Type: {server_response_proto.error.error_type}"
                    logger.error(error_msg)
                    raise LensAPIError(
                        error_msg,
                        status_code=response.status_code,
                        response_body=response_bytes.decode(errors="replace"),
                    )

                if (
                    server_response_proto.objects_response
                    and server_response_proto.objects_response.cluster_info
                ):
                    self.last_cluster_info = (
                        server_response_proto.objects_response.cluster_info
                    )
                    if (
                        self.last_cluster_info
                        and self.last_cluster_info.server_session_id
                    ):
                        logger.debug(
                            f"RequestHandler: Updated last_cluster_info. ServerSessionID: {self.last_cluster_info.server_session_id}, "
                            f"RoutingInfo available: {bool(self.last_cluster_info.routing_info)}"
                        )
                else:
                    self.last_cluster_info = None
                    logger.debug(
                        "RequestHandler: No cluster_info in response or no objects_response."
                    )

                return server_response_proto

            except httpx.HTTPStatusError as e_http:
                response_text_content = e_http.response.text
                logger.error(
                    f"HTTP error: {e_http.response.status_code} - {response_text_content[:500]}",
                    exc_info=True,
                )
                raise LensAPIError(
                    f"HTTP ошибка: {e_http.response.status_code}",
                    status_code=e_http.response.status_code,
                    response_body=response_text_content,
                ) from e_http
            except httpx.RequestError as e_req:
                logger.error(
                    f"Request error (possibly proxy-related): {e_req}", exc_info=True
                )
                raise LensAPIError(
                    f"Ошибка сети или запроса (возможно, связана с прокси): {e_req}"
                ) from e_req
            except (LensProtobufError, ValueError) as e_parse:
                logger.error(
                    f"Error parsing Protobuf response: {e_parse}", exc_info=True
                )
                try:
                    decoded_for_error = response_bytes.decode(errors="replace")
                except AttributeError:
                    decoded_for_error = str(response_bytes)
                raise LensProtobufError(
                    f"Protobuf response parsing error: {e_parse}",
                    response_body=decoded_for_error,
                ) from e_parse
            except Exception as e_gen:
                logger.error(f"Unexpected error during request: {e_gen}", exc_info=True)
                raise LensAPIError(
                    f"Unexpected error while executing the request: {e_gen}"
                )
