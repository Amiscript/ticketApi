from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, enum_column
from models.event import Seat


class OrderStatus(StrEnum):
    CONFIRMED = "confirmed"  # tickets issued immediately
    CANCELLED = "cancelled"  # cancelled by the customer or an admin


class TicketStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"  # seat / inventory freed


# Tickets in these states "hold" inventory.
ACTIVE_TICKET_STATUSES = (TicketStatus.CONFIRMED,)


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(
        enum_column(OrderStatus), default=OrderStatus.CONFIRMED, index=True
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    tickets: Mapped[list["Ticket"]] = relationship(
        back_populates="order", lazy="selectin", order_by="Ticket.id"
    )


class Ticket(TimestampMixin, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        # THE safety net against double-booking a seat: at most one active ticket per seat.
        Index(
            "uq_ticket_active_seat",
            "seat_id",
            unique=True,
            postgresql_where=text("seat_id IS NOT NULL AND status = 'confirmed'"),
            sqlite_where=text("seat_id IS NOT NULL AND status = 'confirmed'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    ticket_type_id: Mapped[int] = mapped_column(
        ForeignKey("ticket_types.id"), index=True
    )
    seat_id: Mapped[int | None] = mapped_column(ForeignKey("seats.id"), default=None)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # price when booked
    status: Mapped[TicketStatus] = mapped_column(
        enum_column(TicketStatus), default=TicketStatus.CONFIRMED
    )
    code: Mapped[str] = mapped_column(
        String(36), unique=True, default=lambda: str(uuid4())
    )

    order: Mapped[Order] = relationship(back_populates="tickets")
    seat: Mapped[Seat | None] = relationship(lazy="selectin")
