class LensException(Exception):
    """Base class for exceptions of this library."""

    pass


class LensAPIError(LensException):
    """Exception for errors related to HTTP requests to the Lens API."""

    def __init__(self, message, status_code=None, response_body=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body

    def __str__(self):
        msg = super().__str__()
        if self.status_code:
            msg += f" (Status Code: {self.status_code})"
        if self.response_body:
            response_body_str = str(self.response_body)
            if len(response_body_str) > 200:
                response_body_str = response_body_str[:200] + "..."
            msg += f"\nResponse Body (partial): {response_body_str}"
        return msg


class LensImageError(LensException):
    """Exception for errors related to image processing."""

    pass


class LensProtobufError(LensException):
    """Exception for errors related to the creation or parsing of Protobuf messages."""

    pass


class LensFontError(LensException):
    """Exception for font-related errors."""

    pass


class LensConfigError(LensException):
    """Exception for configuration-related errors."""

    pass
