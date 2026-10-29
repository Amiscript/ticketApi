from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models import EventStatus


def _validate_start(value: datetime | None) -> datetime | None:
    if value is None:
        return value
    if value.tzinfo is None:
        raise ValueError("starts_at must include a timezone, e.g. 2026-12-01T18:00:00Z")
    if value <= datetime.now(UTC):
        raise ValueError("starts_at must be in the future")
    return value


class TicketTypeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    quantity: int = Field(default=0, ge=0, le=1_000_000)


class TicketTypeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=80)
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    quantity: int | None = Field(default=None, ge=0, le=1_000_000)


class TicketTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    name: str
    price: Decimal
    quantity: int
    available: int | None = None


class EventCreate(BaseModel):
    name: str = Field(min_length=3, max_length=150)
    description: str = Field(default="", max_length=5000)
    venue: str = Field(min_length=2, max_length=200)
    starts_at: datetime
    is_seated: bool = False

    @field_validator("starts_at")
    @classmethod
    def check_start(cls, value: datetime) -> datetime:
        return _validate_start(value)


class EventUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=150)
    description: str | None = Field(default=None, max_length=5000)
    venue: str | None = Field(default=None, min_length=2, max_length=200)
    starts_at: datetime | None = None

    @field_validator("starts_at")
    @classmethod
    def check_start(cls, value: datetime | None) -> datetime | None:
        return _validate_start(value)


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organizer_id: int
    name: str
    description: str
    venue: str
    starts_at: datetime
    is_seated: bool
    status: EventStatus
    rejection_reason: str | None
    ticket_types: list[TicketTypeOut] = []


class TypeSales(BaseModel):
    ticket_type_id: int
    name: str
    capacity: int
    booked: int
    value: Decimal


class SalesOut(BaseModel):
    event_id: int
    total_booked: int
    total_value: Decimal
    by_ticket_type: list[TypeSales]


class SeatGenerate(BaseModel):
    ticket_type_id: int
    section: str = Field(min_length=1, max_length=40)
    rows: int = Field(ge=1, le=26, description="Rows are labelled A, B, C...")
    seats_per_row: int = Field(ge=1, le=100)


class SeatOut(BaseModel):
    id: int
    section: str
    row: str
    number: int
    ticket_type_id: int
    status: str
