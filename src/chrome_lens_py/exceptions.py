class LensCookieError(Exception):
    """Custom exception for errors related to cookies."""
    pass


class LensImageError(Exception):
    """Custom exception for errors related to image processing."""
    pass


class LensAPIError(Exception):
    """Custom exception for errors related to the LensAPI."""
    pass


class LensParsingError(Exception):
    """Custom exception for errors related to parsing Lens output."""
    pass


class LensError(Exception):
    """Class for error handling."""

    def __init__(self, message, code=None, headers=None, body=None):
        super().__init__(message)
        self.code = code
        self.headers = headers
        self.body = body
