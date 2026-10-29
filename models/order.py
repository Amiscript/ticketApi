from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, enum_column
from models.event import Seat


class OrderStatus(StrEnum):
    PENDING = "pending"  # seats/tickets reserved, waiting for payment
    PAID = "paid"
    CANCELLED = "cancelled"  # customer cancelled before paying
    EXPIRED = "expired"  # reservation timed out
    REFUNDED = "refunded"


class TicketStatus(StrEnum):
    RESERVED = "reserved"
    CONFIRMED = "confirmed"
    RELEASED = "released"  # reservation freed (cancelled / expired)
    REFUNDED = "refunded"


# Tickets in these states "hold" inventory.
ACTIVE_TICKET_STATUSES = (TicketStatus.RESERVED, TicketStatus.CONFIRMED)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus), default=OrderStatus.PENDING, index=True
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payment_reference: Mapped[str | None] = mapped_column(
        String(100), index=True, default=None
    )

    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="order", lazy="selectin", order_by="Ticket.id"
    )


class Ticket(TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        # THE safety net against double-selling a seat: at most one active ticket per seat.
        Index(
            "uq_ticket_active_seat",
            "seat_id",
            unique=True,
            postgresql_where=text(
                "seat_id IS NOT NULL AND status IN ('reserved', 'confirmed')"
            ),
            sqlite_where=text(
                "seat_id IS NOT NULL AND status IN ('reserved', 'confirmed')"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    ticket_type_id: Mapped[int] = mapped_column(
        ForeignKey("ticket_types.id"), index=True
    )
    seat_id: Mapped[int | None] = mapped_column(ForeignKey("seats.id"), default=None)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # price at time of purchase
    status: Mapped[TicketStatus] = mapped_column(
        enum_column(TicketStatus), default=TicketStatus.RESERVED
    )
    code: Mapped[str] = mapped_column(
        String(36), unique=True, default=lambda: str(uuid4())
    )

    order: Mapped[Order] = relationship(back_populates="tickets")
    seat: Mapped[Seat | None] = relationship(lazy="selectin")
