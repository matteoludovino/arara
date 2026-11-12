from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class DomainError(Exception):
    """A business rule said no. The message is shown to the user, so it is in Portuguese."""

    status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(self, message: str, code: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


class ConflictError(DomainError):
    """The request is valid, but the current state (stock, a closed till...) doesn't allow it."""

    status_code: int = status.HTTP_409_CONFLICT


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, DomainError):
        return Response({"detail": exc.message, "code": exc.code, **exc.details}, status=exc.status_code)
    return exception_handler(exc, context)
