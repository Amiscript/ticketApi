from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models import OrderStatus, TicketStatus


class OrderItem(BaseModel):
    ticket_type_id: int
    quantity: int = Field(ge=1, le=100)


class OrderCreate(BaseModel):
    event_id: int
    items: list[OrderItem] = Field(default_factory=list)
    seat_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def exactly_one_mode(self):
        if bool(self.items) == bool(self.seat_ids):
            raise ValueError(
                "Provide either 'items' (general admission) or 'seat_ids' (seated), not both or neither"
            )
        return self


class SeatBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    section: str
    row: str
    number: int


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    status: TicketStatus
    ticket_type_id: int
    price: Decimal
    seat: SeatBrief | None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    status: OrderStatus
    total_amount: Decimal
    created_at: datetime
    tickets: list[TicketOut]
