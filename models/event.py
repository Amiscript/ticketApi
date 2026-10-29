from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin, enum_column


class EventStatus(StrEnum):
    PENDING = "pending"  # waiting for admin review
    APPROVED = "approved"  # visible + purchasable
    REJECTED = "rejected"
    SUSPENDED = "suspended"  # was approved, pulled by an admin


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    organizer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str] = mapped_column(Text, default="")
    venue: Mapped[str] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    is_seated: Mapped[bool] = mapped_column(default=False)
    status: Mapped[EventStatus] = mapped_column(
        enum_column(EventStatus), default=EventStatus.PENDING, index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), default=None)

    ticket_types: Mapped[list["TicketType"]] = relationship(
        back_populates="event",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="TicketType.id",
    )


class TicketType(Base):
    __tablename__ = "ticket_types"
    __table_args__ = (
        UniqueConstraint("event_id", "name", name="uq_ticket_type_event_name"),
        CheckConstraint("quantity >= 0", name="ck_ticket_type_quantity_nonneg"),
        CheckConstraint("price >= 0", name="ck_ticket_type_price_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # General admission: total tickets on sale. Seated events: grows as seats are generated.
    quantity: Mapped[int] = mapped_column(default=0)

    event: Mapped[Event] = relationship(back_populates="ticket_types")


class Seat(Base):
    __tablename__ = "seats"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "section", "row", "number", name="uq_seat_position"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), index=True
    )
    ticket_type_id: Mapped[int] = mapped_column(
        ForeignKey("ticket_types.id", ondelete="CASCADE"), index=True
    )
    section: Mapped[str] = mapped_column(String(40))
    row: Mapped[str] = mapped_column(String(10))
    number: Mapped[int]

    ticket_type: Mapped[TicketType] = relationship()
