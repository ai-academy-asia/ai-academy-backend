"""Domain-level error used by the service layer.

Services raise ``ServiceError(status, code, **extra)`` instead of touching Flask.
``create_app`` registers an error handler that renders it as
``{"error": code, ...extra}`` with the given HTTP status — so routes stay thin
and services stay framework-agnostic (apart from this one exception type)."""


class ServiceError(Exception):
    def __init__(self, status: int, code: str, **extra):
        super().__init__(code)
        self.status = status
        self.code = code
        self.extra = extra
