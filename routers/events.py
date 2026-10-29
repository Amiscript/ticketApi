from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from core.exceptions import ConflictError, ForbiddenError, NotFoundError
from dependencies import CurrentOrganizer, CurrentUser, DbSession, OptionalUser
from models import Event, EventStatus, Order, Role, Ticket, TicketStatus
from schemas.event import EventCreate, EventOut, EventUpdate, SalesOut, TypeSales
from services.events import get_owned_event, get_visible_event

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("", response_model=list[EventOut])
def browse_events(
    db: DbSession,
    q: str | None = Query(None, description="Search name or venue"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):

    stmt = select(Event).where(
        Event.status == EventStatus.APPROVED, Event.starts_at > datetime.now(UTC)
    )
    if q:
        stmt = stmt.where(
            or_(
                Event.name.icontains(q, autoescape=True),
                Event.venue.icontains(q, autoescape=True),
            )
        )
    return db.scalars(stmt.order_by(Event.starts_at).offset(skip).limit(limit)).all()


@router.post("", response_model=EventOut, status_code=201)
def create_event(data: EventCreate, user: CurrentOrganizer, db: DbSession):
    """Organizers create events. They start as `pending` until an admin approves them."""
    event = Event(organizer_id=user.id, **data.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/mine", response_model=list[EventOut])
def my_events(user: CurrentOrganizer, db: DbSession):
    return db.scalars(
        select(Event)
        .where(Event.organizer_id == user.id)
        .order_by(Event.starts_at.desc())
    ).all()


@router.get("/{event_id}", response_model=EventOut)
def get_event(event_id: int, db: DbSession, user: OptionalUser):
    return get_visible_event(db, event_id, user)


@router.patch("/{event_id}", response_model=EventOut)
def update_event(
    event_id: int, data: EventUpdate, user: CurrentOrganizer, db: DbSession
):
    event = get_owned_event(db, event_id, user)
    # exclude_none: a client sending {"name": null} must not wipe a NOT NULL column (was a 500)
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(event, field, value)
    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: int, user: CurrentOrganizer, db: DbSession):
    event = get_owned_event(db, event_id, user)
    if db.scalar(select(Order.id).where(Order.event_id == event.id).limit(1)):
        raise ConflictError("This event already has orders and cannot be deleted")
    db.delete(event)
    db.commit()


@router.get("/{event_id}/sales", response_model=SalesOut)
def event_sales(event_id: int, user: CurrentUser, db: DbSession):
    """How many tickets are booked? (organizer who owns the event, or an admin)"""
    event = db.get(Event, event_id)
    if event is None:
        raise NotFoundError("Event not found")
    if user.role != Role.ADMIN and event.organizer_id != user.id:
        raise ForbiddenError("You do not own this event")

    rows = db.execute(
        select(
            Ticket.ticket_type_id,
            func.count(Ticket.id),
            func.coalesce(func.sum(Ticket.price), 0),
        )
        .where(Ticket.event_id == event_id, Ticket.status == TicketStatus.CONFIRMED)
        .group_by(Ticket.ticket_type_id)
    ).all()
    sales = {type_id: (count, revenue) for type_id, count, revenue in rows}

    by_type = [
        TypeSales(
            ticket_type_id=tt.id,
            name=tt.name,
            capacity=tt.quantity,
            booked=sales.get(tt.id, (0, Decimal(0)))[0],
            value=sales.get(tt.id, (0, Decimal(0)))[1],
        )
        for tt in event.ticket_types
    ]
    return SalesOut(
        event_id=event_id,
        total_booked=sum(t.booked for t in by_type),
        total_value=sum((t.value for t in by_type), Decimal(0)),
        by_ticket_type=by_type,
    )
