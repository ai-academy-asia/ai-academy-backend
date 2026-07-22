"""Service layer: domain/business logic used by the actor routers.

Routes (student / teacher / admin) parse the request and call these; the logic
(validation, conflict detection, provisioning, enrollment, scheduling) lives
here, not in the routes."""
from .errors import ServiceError

__all__ = ["ServiceError"]
