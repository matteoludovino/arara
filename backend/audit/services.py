from typing import Any

from django.db import models

from accounts.models import User
from locations.models import Location

from .models import AuditEvent


def record(
    *,
    actor: User,
    action: str,
    location: Location | None = None,
    target: models.Model | None = None,
    data: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        location=location,
        target_type=target._meta.label_lower if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        data=data or {},
    )
