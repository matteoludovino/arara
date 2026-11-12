"""
Transfers. The origin's team creates and dispatches; the destination's team receives. Each
step locks the transfer row first, then stock (through post_entry), the system's lock order.
"""

from django.db import connection, transaction
from django.utils import timezone

from accounts.capabilities import Capability, can
from accounts.models import User
from audit.services import record
from catalog.models import ProductVariant
from common.errors import ConflictError, DomainError
from locations.models import Location
from stock.models import StockEntry
from stock.services import Operation, post_entry
from stock.services import Transfer as Move

from .models import Transfer, TransferLine

Status = Transfer.Status


def next_number() -> str:
    with connection.cursor() as cursor:
        cursor.execute("select nextval('transfers_number_seq')")
        (serial,) = cursor.fetchone()
    return f"TR-{serial:06d}"


def _require(user: User, location: Location, side: str) -> None:
    if not can(user, Capability.STOCK_TRANSFER, location):
        raise DomainError(f"Você não trabalha na loja de {side} desta transferência.", "transfer_not_allowed")


def _locked(transfer: Transfer) -> Transfer:
    return Transfer.objects.select_for_update(of=("self",)).select_related("origin", "destination").get(pk=transfer.pk)


def _check_lines(lines: list[tuple[ProductVariant, int]]) -> None:
    if not lines or any(quantity <= 0 for _, quantity in lines):
        raise DomainError("Informe as peças a transferir.", "transfer_empty")
    if len({variant.pk for variant, _ in lines}) != len(lines):
        raise DomainError("SKU repetido na transferência.", "transfer_duplicate_sku")


@transaction.atomic
def create(
    *, user: User, origin: Location, destination: Location, lines: list[tuple[ProductVariant, int]], notes: str = ""
) -> Transfer:
    _require(user, origin, "origem")
    if not (origin.is_physical and destination.is_physical):
        raise DomainError("Transferências são entre lojas e depósitos.", "location_not_physical")
    if origin.pk == destination.pk:
        raise DomainError("Origem e destino são o mesmo local.", "transfer_same_location")
    _check_lines(lines)
    transfer = Transfer.objects.create(
        number=next_number(), origin=origin, destination=destination, notes=notes, created_by=user
    )
    TransferLine.objects.bulk_create(TransferLine(transfer=transfer, variant=v, quantity_sent=q) for v, q in lines)
    return transfer


@transaction.atomic
def replace_lines(*, user: User, transfer: Transfer, lines: list[tuple[ProductVariant, int]]) -> Transfer:
    transfer = _locked(transfer)
    _require(user, transfer.origin, "origem")
    if transfer.status != Status.DRAFT:
        raise ConflictError("Só um rascunho tem os itens alterados.", "transfer_not_draft")
    _check_lines(lines)
    transfer.lines.all().delete()
    TransferLine.objects.bulk_create(TransferLine(transfer=transfer, variant=v, quantity_sent=q) for v, q in lines)
    return transfer


@transaction.atomic
def dispatch(*, user: User, transfer: Transfer) -> Transfer:
    transfer = _locked(transfer)
    _require(user, transfer.origin, "origem")
    if transfer.status != Status.DRAFT:
        raise ConflictError("Esta transferência já foi enviada.", "transfer_not_draft")
    transit = Location.objects.get(kind=Location.Kind.TRANSIT)
    transfer.dispatch_entry = post_entry(
        kind=StockEntry.Kind.TRANSFER_DISPATCH,
        operations=[
            Move(line.variant_id, transfer.origin_id, transit.pk, line.quantity_sent) for line in transfer.lines.all()
        ],
        user=user,
        source_ref=f"transfer:{transfer.number}",
    )
    transfer.status = Status.IN_TRANSIT
    transfer.dispatched_by, transfer.dispatched_at = user, timezone.now()
    transfer.save(update_fields=["status", "dispatch_entry", "dispatched_by", "dispatched_at"])
    return transfer


@transaction.atomic
def receive(*, user: User, transfer: Transfer, received: dict[int, int], missing_reason: str = "") -> Transfer:
    """
    `received` maps each line id to the pieces that arrived. Whatever didn't arrive leaves
    transit as a loss, with a reason: the shortage is on record, not silently absorbed.
    """
    transfer = _locked(transfer)
    _require(user, transfer.destination, "destino")
    if transfer.status != Status.IN_TRANSIT:
        raise ConflictError("Esta transferência não está em trânsito.", "transfer_not_in_transit")
    lines = list(transfer.lines.select_related("variant"))
    if set(received) != {line.pk for line in lines}:
        raise DomainError("Informe a quantidade recebida de cada item.", "transfer_receipt_incomplete")
    transit = Location.objects.get(kind=Location.Kind.TRANSIT)
    losses = Location.objects.get(kind=Location.Kind.LOSS)
    operations: list[Operation] = []
    missing: list[dict[str, object]] = []
    for line in lines:
        arrived = received[line.pk]
        if not 0 <= arrived <= line.quantity_sent:
            raise DomainError(
                f"{line.variant.sku}: recebido {arrived}, enviado {line.quantity_sent}.", "transfer_receipt_invalid"
            )
        if arrived:
            operations.append(Move(line.variant_id, transit.pk, transfer.destination_id, arrived))
        if arrived < line.quantity_sent:
            operations.append(Move(line.variant_id, transit.pk, losses.pk, line.quantity_sent - arrived))
            missing.append({"sku": line.variant.sku, "sent": line.quantity_sent, "received": arrived})
        line.quantity_received = arrived
    if missing and not missing_reason.strip():
        raise DomainError("Chegou menos do que foi enviado: informe o motivo.", "transfer_missing_reason")
    transfer.receipt_entry = post_entry(
        kind=StockEntry.Kind.TRANSFER_RECEIPT,
        operations=operations,
        user=user,
        source_ref=f"transfer:{transfer.number}",
        reason=StockEntry.Reason.OTHER if missing else "",
        note=missing_reason,
    )
    TransferLine.objects.bulk_update(lines, ["quantity_received"])
    transfer.status = Status.RECEIVED
    transfer.received_by, transfer.received_at = user, timezone.now()
    transfer.save(update_fields=["status", "receipt_entry", "received_by", "received_at"])
    if missing:
        record(
            actor=user,
            action="transfer.shortage",
            location=transfer.destination,
            target=transfer,
            data={"number": transfer.number, "reason": missing_reason, "lines": missing},
        )
    return transfer


@transaction.atomic
def cancel(*, user: User, transfer: Transfer, reason: str) -> Transfer:
    """A draft just ends; a transfer on the road comes back to the origin."""
    transfer = _locked(transfer)
    _require(user, transfer.origin, "origem")
    if transfer.status not in (Status.DRAFT, Status.IN_TRANSIT):
        raise ConflictError("Esta transferência já foi encerrada.", "transfer_finished")
    if transfer.status == Status.IN_TRANSIT:
        transit = Location.objects.get(kind=Location.Kind.TRANSIT)
        transfer.cancel_entry = post_entry(
            kind=StockEntry.Kind.TRANSFER_RECEIPT,
            operations=[
                Move(line.variant_id, transit.pk, transfer.origin_id, line.quantity_sent)
                for line in transfer.lines.all()
            ],
            user=user,
            source_ref=f"transfer:{transfer.number}",
            note=f"Cancelada: {reason}",
        )
    transfer.status = Status.CANCELLED
    transfer.cancelled_at, transfer.cancel_reason = timezone.now(), reason
    transfer.save(update_fields=["status", "cancel_entry", "cancelled_at", "cancel_reason"])
    record(actor=user, action="transfer.cancelled", location=transfer.origin, target=transfer, data={"reason": reason})
    return transfer
