from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.exceptions import BadRequestError, ConflictError, NotFoundError
from dependencies import CurrentOrganizer, DbSession, OptionalUser
from models import ACTIVE_TICKET_STATUSES, Seat, Ticket, TicketType
from schemas.event import SeatGenerate, SeatOut
from services.events import get_owned_event, get_visible_event
from services.orders import release_expired_reservations


router = APIRouter(prefix="/events/{event_id}/seats", tags=["Seats"])


@router.post("/generate", status_code=201)
def generate_seats(
    event_id: int, data: SeatGenerate, user: CurrentOrganizer, db: DbSession
):
    """Create a block of seats, e.g. section 'Floor', 5 rows (A-E) x 10 seats, all VIP."""
    event = get_owned_event(db, event_id, user)
    if not event.is_seated:
        raise BadRequestError("This event is not a seated event")
    tt = db.get(TicketType, data.ticket_type_id)
    if tt is None or tt.event_id != event.id:
        raise NotFoundError("Ticket type not found for this event")

    seats = [
        Seat(
            event_id=event.id,
            ticket_type_id=tt.id,
            section=data.section,
            row=chr(ord("A") + r),
            number=n,
        )
        for r in range(data.rows)
        for n in range(1, data.seats_per_row + 1)
    ]
    db.add_all(seats)
    tt.quantity += len(seats)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"Some seats in section '{data.section}' already exist"
        ) from exc
    return {"created": len(seats), "ticket_type_id": tt.id, "section": data.section}


@router.get("", response_model=list[SeatOut])
def seat_map(
    event_id: int,
    db: DbSession,
    user: OptionalUser,
    section: str | None = Query(None),
    ticket_type_id: int | None = Query(None),
):
    """The 'seat map': every seat with `available` or `taken` status."""
    get_visible_event(db, event_id, user)
    release_expired_reservations(db)

    taken = set(
        db.scalars(
            select(Ticket.seat_id).where(
                Ticket.event_id == event_id,
                Ticket.seat_id.is_not(None),
                Ticket.status.in_(ACTIVE_TICKET_STATUSES),
            )
        )
    )
    stmt = select(Seat).where(Seat.event_id == event_id)
    if section:
        stmt = stmt.where(Seat.section == section)
    if ticket_type_id:
        stmt = stmt.where(Seat.ticket_type_id == ticket_type_id)
    seats = db.scalars(stmt.order_by(Seat.section, Seat.row, Seat.number)).all()
    return [
        SeatOut(
            id=s.id,
            section=s.section,
            row=s.row,
            number=s.number,
            ticket_type_id=s.ticket_type_id,
            status="taken" if s.id in taken else "available",
        )
        for s in seats
    ]
