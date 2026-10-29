# pyrefly: ignore[missing-import]
from core.exceptions import BadRequestError, ConflictError, NotFoundError
from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from dependencies import CurrentOrganizer, DbSession, OptionalUser
from models import Seat, Ticket, TicketType
from schemas.event import TicketTypeCreate, TicketTypeOut, TicketTypeUpdate
from services.events import get_owned_event, get_visible_event
from services.orders import release_expired_reservations, sold_count, sold_counts

router = APIRouter(prefix="/events/{event_id}/ticket-types", tags=["Ticket Types"])


def _with_availability(tt: TicketType, sold: int) -> TicketTypeOut:
    out = TicketTypeOut.model_validate(tt)
    out.available = max(tt.quantity - sold, 0)
    return out


def _get_type(db, event_id: int, ticket_type_id: int) -> TicketType:
    tt = db.get(TicketType, ticket_type_id)
    if tt is None or tt.event_id != event_id:
        raise NotFoundError("Ticket type not found")
    return tt


@router.post("", response_model=TicketTypeOut, status_code=201)
def create_ticket_type(
    event_id: int, data: TicketTypeCreate, user: CurrentOrganizer, db: DbSession
):
    event = get_owned_event(db, event_id, user)
    if not event.is_seated and data.quantity < 1:
        raise BadRequestError(
            "quantity must be at least 1 for general admission events"
        )
    if event.is_seated and data.quantity:
        raise BadRequestError(
            "For seated events, quantity comes from the seats you generate"
        )
    tt = TicketType(event_id=event.id, **data.model_dump())
    db.add(tt)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"A ticket type named '{data.name}' already exists"
        ) from exc
    db.refresh(tt)
    return _with_availability(tt, 0)


@router.get("", response_model=list[TicketTypeOut])
def list_ticket_types(event_id: int, db: DbSession, user: OptionalUser):
    event = get_visible_event(db, event_id, user)
    release_expired_reservations(db)
    sold = sold_counts(db, event.id)  # one query instead of one per ticket type
    return [_with_availability(tt, sold.get(tt.id, 0)) for tt in event.ticket_types]


@router.patch("/{ticket_type_id}", response_model=TicketTypeOut)
def update_ticket_type(
    event_id: int,
    ticket_type_id: int,
    data: TicketTypeUpdate,
    user: CurrentOrganizer,
    db: DbSession,
):
    event = get_owned_event(db, event_id, user)
    tt = _get_type(db, event.id, ticket_type_id)
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if "quantity" in changes:
        if event.is_seated:
            raise BadRequestError(
                "Seated capacity is controlled by the seats you generate"
            )
        if changes["quantity"] < sold_count(db, tt.id):
            raise ConflictError(
                "Cannot set quantity below the number of tickets already sold"
            )
    for field, value in changes.items():
        setattr(tt, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Another ticket type already uses that name") from exc
    return _with_availability(tt, sold_count(db, tt.id))


@router.delete("/{ticket_type_id}", status_code=204)
def delete_ticket_type(
    event_id: int, ticket_type_id: int, user: CurrentOrganizer, db: DbSession
):
    event = get_owned_event(db, event_id, user)
    tt = _get_type(db, event.id, ticket_type_id)
    if db.scalar(select(Ticket.id).where(Ticket.ticket_type_id == tt.id).limit(1)):
        raise ConflictError("Tickets of this type were already sold or reserved")
    if db.scalar(select(Seat.id).where(Seat.ticket_type_id == tt.id).limit(1)):
        raise ConflictError("Seats are assigned to this ticket type")
    db.delete(tt)
    db.commit()
