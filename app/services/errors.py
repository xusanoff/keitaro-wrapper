class ServiceError(Exception):
    """Business-rule violation; message is safe to show to the user."""

    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409
