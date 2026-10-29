from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, select

from dependencies import CurrentAdmin, DbSession, require_roles
from exceptions import BadRequestError, ConflictError, NotFoundError
from services.audit import log_action
from services.email import send_refund_email
from services.orders import refund_order
from models import (
    AuditLog,
    Event,
    EventStatus,
    Order,
    OrderStatus,
    Role,
    Ticket,
    TicketStatus,
    User,
    UserStatus,
)
from schemas.admin import (
    AuditLogOut,
    DashboardOut,
    EventSales,
    ReasonIn,
    RefundIn,
    SalesReport,
    UserStatusUpdate,
)
from schemas.auth import UserOut
from schemas.event import EventOut
from schemas.order import OrderOut

# Every route in this router requires an admin.
router = APIRouter(
    prefix="/admin", tags=["Admin"], dependencies=[Depends(require_roles(Role.ADMIN))]
)


# ---------------------------------------------------------------- dashboard & reports
@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: DbSession):
    users_by_role = {
        r.value: c
        for r, c in db.execute(
            select(User.role, func.count(User.id)).group_by(User.role)
        )
    }
    events_by_status = {
        s.value: c
        for s, c in db.execute(
            select(Event.status, func.count(Event.id)).group_by(Event.status)
        )
    }
    paid_orders, revenue = db.execute(
        select(
            func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0)
        ).where(Order.status == OrderStatus.PAID)
    ).one()
    return DashboardOut(
        total_users=sum(users_by_role.values()),
        users_by_role=users_by_role,
        events_by_status=events_by_status,
        paid_orders=paid_orders,
        gross_revenue=revenue,
    )


@router.get("/reports/sales", response_model=SalesReport)
def sales_report(
    db: DbSession,
    start: datetime | None = Query(
        None, description="Include orders created on/after this time"
    ),
    end: datetime | None = Query(
        None, description="Include orders created before this time"
    ),
):
    def window(stmt):
        if start:
            stmt = stmt.where(Order.created_at >= start)
        if end:
            stmt = stmt.where(Order.created_at < end)
        return stmt

    def totals(status: OrderStatus):
        return db.execute(
            window(
                select(
                    func.count(Order.id), func.coalesce(func.sum(Order.total_amount), 0)
                ).where(Order.status == status)
            )
        ).one()

    paid_count, gross = totals(OrderStatus.PAID)
    refunded_count, refunded_amount = totals(OrderStatus.REFUNDED)
    tickets_sold = db.scalar(
        window(
            select(func.count(Ticket.id))
            .join(Order, Order.id == Ticket.order_id)
            .where(Ticket.status == TicketStatus.CONFIRMED)
        )
    )
    top = db.execute(
        window(
            select(
                Event.id, Event.name, func.count(Order.id), func.sum(Order.total_amount)
            )
            .join(Order, Order.event_id == Event.id)
            .where(Order.status == OrderStatus.PAID)
        )
        .group_by(Event.id, Event.name)
        .order_by(func.sum(Order.total_amount).desc())
        .limit(10)
    ).all()

    return SalesReport(
        paid_orders=paid_count,
        tickets_sold=tickets_sold or 0,
        gross_revenue=gross,
        refunded_orders=refunded_count,
        refunded_amount=refunded_amount,
        top_events=[
            EventSales(event_id=i, name=n, orders=c, revenue=r) for i, n, c, r in top
        ],
    )


# ---------------------------------------------------------------- users
@router.get("/users", response_model=list[UserOut])
def list_users(
    db: DbSession,
    role: Role | None = None,
    status: UserStatus | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if status:
        stmt = stmt.where(User.status == status)
    return db.scalars(stmt.order_by(User.id).offset(skip).limit(limit)).all()


@router.patch("/users/{user_id}/status", response_model=UserOut)
def set_user_status(
    user_id: int, data: UserStatusUpdate, admin: CurrentAdmin, db: DbSession
):
    """Suspend, ban or re-activate a user."""
    target = db.get(User, user_id)
    if target is None:
        raise NotFoundError("User not found")
    if target.id == admin.id:
        raise BadRequestError("You cannot change your own status")
    if target.role == Role.ADMIN:
        raise BadRequestError("Admin accounts cannot be suspended or banned here")
    previous = target.status
    target.status = data.status
    log_action(
        db,
        admin,
        f"user.{data.status.value}",
        "user",
        target.id,
        {"from": previous.value, "reason": data.reason},
    )
    db.commit()
    db.refresh(target)
    return target


# ---------------------------------------------------------------- events (moderation)
@router.get("/events", response_model=list[EventOut])
def list_all_events(
    db: DbSession,
    status: EventStatus | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    stmt = select(Event)
    if status:
        stmt = stmt.where(Event.status == status)
    return db.scalars(stmt.order_by(Event.id.desc()).offset(skip).limit(limit)).all()


def _moderate(
    db, admin, event_id, allowed_from, new_status, action, reason=None
) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise NotFoundError("Event not found")
    if event.status not in allowed_from:
        raise ConflictError(f"Cannot {action} an event that is {event.status}")
    previous = event.status
    event.status = new_status
    event.rejection_reason = reason
    log_action(
        db,
        admin,
        f"event.{action}",
        "event",
        event.id,
        {"from": previous.value, "reason": reason},
    )
    db.commit()
    db.refresh(event)
    return event


@router.post("/events/{event_id}/approve", response_model=EventOut)
def approve_event(event_id: int, admin: CurrentAdmin, db: DbSession):
    return _moderate(
        db,
        admin,
        event_id,
        {EventStatus.PENDING, EventStatus.REJECTED, EventStatus.SUSPENDED},
        EventStatus.APPROVED,
        "approve",
    )


@router.post("/events/{event_id}/reject", response_model=EventOut)
def reject_event(event_id: int, data: ReasonIn, admin: CurrentAdmin, db: DbSession):
    return _moderate(
        db,
        admin,
        event_id,
        {EventStatus.PENDING},
        EventStatus.REJECTED,
        "reject",
        data.reason,
    )


@router.post("/events/{event_id}/suspend", response_model=EventOut)
def suspend_event(event_id: int, data: ReasonIn, admin: CurrentAdmin, db: DbSession):
    return _moderate(
        db,
        admin,
        event_id,
        {EventStatus.APPROVED},
        EventStatus.SUSPENDED,
        "suspend",
        data.reason,
    )


# ---------------------------------------------------------------- refunds
@router.post("/orders/{order_id}/refund", response_model=OrderOut)
def refund(
    order_id: int,
    data: RefundIn,
    background_tasks: BackgroundTasks,
    admin: CurrentAdmin,
    db: DbSession,
):
    order = refund_order(db, order_id)
    log_action(
        db,
        admin,
        "order.refund",
        "order",
        order.id,
        {"amount": str(order.total_amount), "reason": data.reason},
    )
    db.commit()
    db.refresh(order)
    background_tasks.add_task(send_refund_email, order.id)
    return order


# ---------------------------------------------------------------- audit logs
@router.get("/audit-logs", response_model=list[AuditLogOut])
def audit_logs(
    db: DbSession,
    action: str | None = None,
    admin_id: int | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if admin_id:
        stmt = stmt.where(AuditLog.admin_id == admin_id)
    return db.scalars(stmt.order_by(AuditLog.id.desc()).offset(skip).limit(limit)).all()
