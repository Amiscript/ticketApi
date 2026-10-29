from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from models import UserStatus


class UserStatusUpdate(BaseModel):
    status: UserStatus
    reason: str | None = Field(default=None, max_length=500)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class CancelIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    admin_id: int
    action: str
    target_type: str
    target_id: int
    details: dict | None
    created_at: datetime


class DashboardOut(BaseModel):
    total_users: int
    users_by_role: dict[str, int]
    events_by_status: dict[str, int]
    confirmed_orders: int
    total_value: Decimal


class EventSales(BaseModel):
    event_id: int
    name: str
    orders: int
    total_value: Decimal


class SalesReport(BaseModel):
    confirmed_orders: int
    tickets_booked: int
    total_value: Decimal
    cancelled_orders: int
    cancelled_value: Decimal
    top_events: list[EventSales]
