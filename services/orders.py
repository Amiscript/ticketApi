"""Order lifecycle: reserve -> pay -> confirm (or cancel / expire / refund).

Concurrency model: rows that decide availability are locked with SELECT ... FOR UPDATE, and the
partial unique index `uq_ticket_active_seat` is the final guard against double-selling a seat.
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select, update
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
from services import payments


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    # SQLite returns naive datetimes; Postgres returns aware ones.
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ------------------------------------------------------------------ inventory
def sold_counts(db: Session, event_id: int) -> dict[int, int]:
    """ticket_type_id -> tickets currently holding inventory (reserved or confirmed)."""
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


def _release_order(order: Order, order_status: OrderStatus, ticket_status: TicketStatus) -> None:
    order.status = order_status
    for ticket in order.tickets:
        if ticket.status in ACTIVE_TICKET_STATUSES:
            ticket.status = ticket_status


def release_expired_reservations(db: Session) -> int:
    """Expire pending orders past their deadline and free their tickets/seats."""
    expired = db.scalars(
        select(Order)
        .where(Order.status == OrderStatus.PENDING, Order.expires_at < _now())
        .with_for_update(skip_locked=True)
    ).all()
    for order in expired:
        _release_order(order, OrderStatus.EXPIRED, TicketStatus.RELEASED)
    db.commit()
    return len(expired)


# ------------------------------------------------------------------ queries
def get_order(db: Session, order_id: int, user: User, *, lock: bool = False) -> Order:
    stmt = select(Order).where(Order.id == order_id)
    if lock:
        stmt = stmt.with_for_update()
    order = db.scalar(stmt)
    if order is None or (order.user_id != user.id and user.role != Role.ADMIN):
        raise NotFoundError("Order not found")
    return order


# ------------------------------------------------------------------ reserve
def create_order(db: Session, user: User, data: OrderCreate) -> Order:
    release_expired_reservations(db)

    event = db.get(Event, data.event_id)
    if event is None or event.status != EventStatus.APPROVED:
        raise NotFoundError("Event not found")
    if _aware(event.starts_at) <= _now():
        raise BadRequestError("This event has already started")

    if data.seat_ids:
        lines = _reserve_seats(db, event, data.seat_ids)
    else:
        lines = _reserve_general(db, event, data)

    total = sum((price for _, price, _ in lines), Decimal(0))
    order = Order(
        user_id=user.id,
        event_id=event.id,
        status=OrderStatus.PENDING,
        total_amount=total,
        expires_at=_now() + timedelta(minutes=settings.reservation_minutes),
    )
    for type_id, price, seat_id in lines:
        order.tickets.append(
            Ticket(
                event_id=event.id,
                ticket_type_id=type_id,
                seat_id=seat_id,
                price=price,
                status=TicketStatus.RESERVED,
            )
        )
    db.add(order)
    try:
        db.commit()
    except IntegrityError as exc:  # lost a race for a seat despite the locks
        db.rollback()
        raise ConflictError("One or more seats were just taken, please pick others") from exc
    return order


def _reserve_general(db: Session, event: Event, data: OrderCreate):
    if event.is_seated:
        raise BadRequestError("This is a seated event, choose seats with 'seat_ids'")

    wanted: Counter[int] = Counter()
    for item in data.items:
        wanted[item.ticket_type_id] += item.quantity
    if sum(wanted.values()) > settings.max_tickets_per_order:
        raise BadRequestError(f"You can buy at most {settings.max_tickets_per_order} tickets per order")

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


def _reserve_seats(db: Session, event: Event, seat_ids: list[int]):
    if not event.is_seated:
        raise BadRequestError("This event is general admission, use 'items'")
    if len(set(seat_ids)) != len(seat_ids):
        raise BadRequestError("Duplicate seats in request")
    if len(seat_ids) > settings.max_tickets_per_order:
        raise BadRequestError(f"You can buy at most {settings.max_tickets_per_order} tickets per order")

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
        for tt in db.scalars(select(TicketType).where(TicketType.id.in_(list({s.ticket_type_id for s in seats}))))
    }
    return [(s.ticket_type_id, prices[s.ticket_type_id], s.id) for s in seats]


# ------------------------------------------------------------------ pay / confirm
def start_payment(db: Session, user: User, order_id: int):
    order = get_order(db, order_id, user, lock=True)
    if order.user_id != user.id:
        raise NotFoundError("Order not found")
    _require_open(db, order)
    session = payments.initialize(user.email, order.total_amount)
    order.payment_reference = session.reference
    db.commit()
    return order, session


def _require_open(db: Session, order: Order) -> None:
    if order.status != OrderStatus.PENDING:
        raise ConflictError(f"Order is {order.status}")
    if _aware(order.expires_at) < _now():
        _release_order(order, OrderStatus.EXPIRED, TicketStatus.RELEASED)
        db.commit()
        raise ConflictError("This reservation has expired, please start a new order")


def confirm_payment(db: Session, user: User, order_id: int, reference: str):
    """Returns (order, newly_paid). Idempotent: confirming a paid order again is a no-op."""
    order = get_order(db, order_id, user, lock=True)
    if order.user_id != user.id:
        raise NotFoundError("Order not found")
    if order.status == OrderStatus.PAID and order.payment_reference == reference:
        return order, False
    _require_open(db, order)
    if not order.payment_reference or order.payment_reference != reference:
        raise BadRequestError("Payment reference does not match this order")
    if not payments.verify(reference, order.total_amount):
        raise BadRequestError("Payment has not been completed")

    order.status = OrderStatus.PAID
    for ticket in order.tickets:
        ticket.status = TicketStatus.CONFIRMED
    db.commit()
    return order, True


# ------------------------------------------------------------------ cancel / refund
def cancel_order(db: Session, user: User, order_id: int) -> Order:
    order = get_order(db, order_id, user, lock=True)
    if order.user_id != user.id:
        raise NotFoundError("Order not found")
    if order.status != OrderStatus.PENDING:
        raise ConflictError(f"Only pending orders can be cancelled (this one is {order.status})")
    _release_order(order, OrderStatus.CANCELLED, TicketStatus.RELEASED)
    db.commit()
    return order


def refund_order(db: Session, order_id: int) -> Order:
    """Mark a paid order refunded. Does NOT commit: the admin router commits with the audit log."""
    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise NotFoundError("Order not found")
    if order.status != OrderStatus.PAID:
        raise ConflictError(f"Only paid orders can be refunded (this one is {order.status})")
    if order.payment_reference:
        payments.refund(order.payment_reference)
    _release_order(order, OrderStatus.REFUNDED, TicketStatus.REFUNDED)
    db.flush()
    return order
