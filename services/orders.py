from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.config import settings
from core.exceptions import BadRequestError, ConflictError, NotFoundError
from models import (
    ACTIVE_TICKET_STATUSES,
    Event,
    EventStatus,
    Order,
    OrderStatus,
    Role,
    Seat,
    Ticket,
    TicketStatus,
    TicketType,
    User,
)
from schemas.order import OrderCreate


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:

    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def sold_counts(db: Session, event_id: int) -> dict[int, int]:

    rows = db.execute(
        select(Ticket.ticket_type_id, func.count(Ticket.id))
        .where(Ticket.event_id == event_id, Ticket.status.in_(ACTIVE_TICKET_STATUSES))
        .group_by(Ticket.ticket_type_id)
    ).all()
    return {type_id: count for type_id, count in rows}


def sold_count(db: Session, ticket_type_id: int) -> int:
    return (
        db.scalar(
            select(func.count(Ticket.id)).where(
                Ticket.ticket_type_id == ticket_type_id,
                Ticket.status.in_(ACTIVE_TICKET_STATUSES),
            )
        )
        or 0
    )


def get_order(db: Session, order_id: int, user: User, *, lock: bool = False) -> Order:

    stmt = select(Order).where(Order.id == order_id)
    if lock:
        stmt = stmt.with_for_update()
    order = db.scalar(stmt)
    if order is None or (order.user_id != user.id and user.role != Role.ADMIN):
        raise NotFoundError("Order not found")
    return order


def create_order(db: Session, user: User, data: OrderCreate) -> Order:
    event = db.get(Event, data.event_id)
    if event is None or event.status != EventStatus.APPROVED:
        raise NotFoundError("Event not found")
    if _aware(event.starts_at) <= _now():
        raise BadRequestError("This event has already started")

    if data.seat_ids:
        lines = _pick_seats(db, event, data.seat_ids)
    else:
        lines = _pick_general(db, event, data)

    order = Order(
        user_id=user.id,
        event_id=event.id,
        status=OrderStatus.CONFIRMED,
        total_amount=sum((price for _, price, _ in lines), Decimal(0)),
    )
    for type_id, price, seat_id in lines:
        order.tickets.append(
            Ticket(
                event_id=event.id,
                ticket_type_id=type_id,
                seat_id=seat_id,
                price=price,
                status=TicketStatus.CONFIRMED,
            )
        )
    db.add(order)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "One or more seats were just taken, please pick others"
        ) from exc
    return order


def _check_limit(count: int) -> None:
    if count > settings.max_tickets_per_order:
        raise BadRequestError(
            f"You can book at most {settings.max_tickets_per_order} tickets per order"
        )


def _pick_general(db: Session, event: Event, data: OrderCreate):
    if event.is_seated:
        raise BadRequestError("This is a seated event, choose seats with 'seat_ids'")

    wanted: Counter[int] = Counter()
    for item in data.items:
        wanted[item.ticket_type_id] += item.quantity
    _check_limit(sum(wanted.values()))

    # Lock the ticket-type rows (in id order, avoiding deadlocks) so concurrent buyers queue up.
    types = {
        tt.id: tt
        for tt in db.scalars(
            select(TicketType)
            .where(TicketType.id.in_(list(wanted)), TicketType.event_id == event.id)
            .order_by(TicketType.id)
            .with_for_update()
        )
    }
    if set(types) != set(wanted):
        raise NotFoundError("One or more ticket types do not belong to this event")

    sold = sold_counts(db, event.id)
    lines = []
    for type_id, qty in wanted.items():
        tt = types[type_id]
        available = tt.quantity - sold.get(type_id, 0)
        if qty > available:
            raise ConflictError(f"Only {max(available, 0)} '{tt.name}' ticket(s) left")
        lines.extend([(type_id, tt.price, None)] * qty)
    return lines


def _pick_seats(db: Session, event: Event, seat_ids: list[int]):
    if not event.is_seated:
        raise BadRequestError("This event is general admission, use 'items'")
    if len(set(seat_ids)) != len(seat_ids):
        raise BadRequestError("Duplicate seats in request")
    _check_limit(len(seat_ids))

    seats = db.scalars(
        select(Seat)
        .where(Seat.id.in_(seat_ids), Seat.event_id == event.id)
        .order_by(Seat.id)
        .with_for_update()
    ).all()
    if len(seats) != len(seat_ids):
        raise NotFoundError("One or more seats do not belong to this event")

    taken = db.scalars(
        select(Ticket.seat_id).where(
            Ticket.seat_id.in_(seat_ids), Ticket.status.in_(ACTIVE_TICKET_STATUSES)
        )
    ).all()
    if taken:
        raise ConflictError("One or more seats are no longer available")

    prices = {
        tt.id: tt.price
        for tt in db.scalars(
            select(TicketType).where(
                TicketType.id.in_(list({s.ticket_type_id for s in seats}))
            )
        )
    }
    return [(s.ticket_type_id, prices[s.ticket_type_id], s.id) for s in seats]


# ------------------------------------------------------------------ cancel
def _cancel(order: Order) -> None:
    order.status = OrderStatus.CANCELLED
    for ticket in order.tickets:
        ticket.status = TicketStatus.CANCELLED


def cancel_order(db: Session, user: User, order_id: int) -> Order:
    """Customer cancels their own order, any time before the event starts."""
    order = get_order(db, order_id, user, lock=True)
    if order.user_id != user.id:
        raise NotFoundError("Order not found")
    if order.status != OrderStatus.CONFIRMED:
        raise ConflictError(f"This order is already {order.status.value}")
    event = db.get(Event, order.event_id)
    if _aware(event.starts_at) <= _now():
        raise ConflictError("This event has already started")
    _cancel(order)
    db.commit()
    return order


def admin_cancel_order(db: Session, order_id: int) -> Order:
    """Cancel any order. Does NOT commit: the admin router commits together with the audit log."""
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise NotFoundError("Order not found")
    if order.status != OrderStatus.CONFIRMED:
        raise ConflictError(f"This order is already {order.status.value}")
    _cancel(order)
    db.flush()
    return order
