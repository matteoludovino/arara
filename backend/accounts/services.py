from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import authenticate
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone

from audit.services import record
from common.errors import ConflictError, DomainError
from locations.models import Location

from .capabilities import Capability, can
from .models import Approval, User

APPROVAL_TTL = timedelta(minutes=5)


def grant_approval(
    *,
    request: HttpRequest | None,
    requester: User,
    approver_email: str,
    approver_password: str,
    action: Approval.Action,
    location: Location,
    reason: str,
    limit: Decimal | None = None,
) -> Approval:
    """Checks the approver's credentials and authority, then issues a single-use approval."""
    approver = authenticate(request, username=approver_email, password=approver_password)
    if not isinstance(approver, User):
        raise DomainError("E-mail ou senha do aprovador incorretos.", "approval_invalid_credentials")
    if approver.pk == requester.pk:
        raise DomainError("A aprovação precisa ser de outra pessoa.", "approval_same_person")
    if not can(approver, Capability.APPROVALS_GRANT, location):
        raise DomainError("Esta pessoa não pode aprovar nesta loja.", "approval_not_allowed")
    approval = Approval.objects.create(
        action=action,
        approver=approver,
        requested_by=requester,
        location=location,
        reason=reason,
        limit=limit,
        expires_at=timezone.now() + APPROVAL_TTL,
    )
    record(
        actor=approver,
        action="approval.granted",
        location=location,
        target=approval,
        data={"action": action, "requested_by": requester.pk, "reason": reason, "limit": str(limit) if limit else None},
    )
    return approval


def consume_approval(
    *, approval_id: int, requester: User, action: Approval.Action, location: Location, used_by: str
) -> Approval:
    """
    Spends an approval inside the caller's transaction. It must be for this action, this
    person and this location, unexpired and unused; the row lock makes "unused" race-free.
    """
    with transaction.atomic():
        approval = Approval.objects.select_for_update().filter(pk=approval_id).first()
        if (
            approval is None
            or approval.requested_by_id != requester.pk
            or approval.action != action
            or approval.location_id != location.pk
        ):
            raise DomainError("Aprovação não encontrada para esta operação.", "approval_not_found")
        if approval.consumed_at is not None:
            raise ConflictError("Esta aprovação já foi usada.", "approval_used")
        if approval.expires_at <= timezone.now():
            raise ConflictError("A aprovação expirou. Peça de novo.", "approval_expired")
        approval.consumed_at = timezone.now()
        approval.consumed_by_ref = used_by
        approval.save(update_fields=["consumed_at", "consumed_by_ref"])
        return approval
