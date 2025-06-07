class LensException(Exception):
    """Базовый класс для исключений этой библиотеки."""
    pass

class LensAPIError(LensException):
    """Исключение для ошибок, связанных с HTTP запросами к API Lens."""
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
    """Исключение для ошибок, связанных с обработкой изображений."""
    pass

class LensProtobufError(LensException):
    """Исключение для ошибок, связанных с созданием или парсингом Protobuf сообщений."""
    pass

class LensFontError(LensException):
    """Исключение для ошибок, связанных со шрифтами."""
    pass

class LensConfigError(LensException):
    """Исключение для ошибок, связанных с конфигурацией."""
    pass