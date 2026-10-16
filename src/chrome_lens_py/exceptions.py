from typing import Any, Optional


class LensException(Exception):
    """Base class for exceptions of this library."""

    pass


class LensAPIError(LensException):
    """Exception for errors related to HTTP requests to the Lens API."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self) -> str:
        msg = super().__str__()
        if self.status_code:
            msg += f" (Status Code: {self.status_code})"
        if self.response_body:
            response_body_str = str(self.response_body)
            if len(response_body_str) > 200:
                response_body_str = response_body_str[:200] + "..."
            msg += f"\nResponse Body (partial): {response_body_str}"
        return msg


class LensRateLimitError(LensAPIError):
    """The server answered 429 or 503 and the retry budget ran out.

    `retry_after` is the server's Retry-After hint in seconds, when it sent one.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[Any] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message, status_code, response_body)
        self.retry_after = retry_after


class LensAuthError(LensAPIError):
    """The server rejected the API key (401/403) and no fallback key worked."""


class LensTimeoutError(LensAPIError):
    """A request exceeded its read timeout or the overall per-request deadline."""


class LensConnectionError(LensAPIError):
    """The server could not be reached (DNS, TCP, TLS or proxy failure)."""


class LensImageError(LensException):
    """Exception for errors related to image processing."""

    pass


class LensProtobufError(LensException):
    """Exception for errors related to the creation or parsing of Protobuf messages."""

    def __init__(self, message: str, response_body: Optional[Any] = None) -> None:
        super().__init__(message)
        self.response_body = response_body

    def __str__(self) -> str:
        msg = super().__str__()
        if self.response_body:
            body = str(self.response_body)
            if len(body) > 200:
                body = body[:200] + "..."
            msg += f"\nResponse Body (partial): {body}"
        return msg


class LensFontError(LensException):
    """Exception for font-related errors."""

    pass


class LensConfigError(LensException):
    """Exception for configuration-related errors."""

    pass
