from fastapi import APIRouter, BackgroundTasks, Request, Response
from sqlalchemy import select

from core.config import settings
from core.exceptions import ConflictError, NotFoundError
from core.rate_limit import limiter
from dependencies import CurrentUser, DbSession
from models import Order, Role, Ticket, TicketStatus
from schemas.order import OrderCreate, OrderOut
from services import orders as order_service
from services.email import send_ticket_email
from services.qr import generate_qr_png

router = APIRouter(prefix="/orders", tags=["Orders"])
tickets_router = APIRouter(prefix="/tickets", tags=["Tickets"])


@router.post("", response_model=OrderOut, status_code=201)
@limiter.limit(settings.rate_limit_purchase)
def book(
    request: Request,
    data: OrderCreate,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: DbSession,
):

    order = order_service.create_order(db, user, data)
    background_tasks.add_task(send_ticket_email, order.id)
    return order


@router.get("", response_model=list[OrderOut])
def my_orders(user: CurrentUser, db: DbSession):
    return db.scalars(
        select(Order).where(Order.user_id == user.id).order_by(Order.id.desc())
    ).all()


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, user: CurrentUser, db: DbSession):
    return order_service.get_order(db, order_id, user)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel(order_id: int, user: CurrentUser, db: DbSession):
    return order_service.cancel_order(db, user, order_id)


@tickets_router.get(
    "/{ticket_id}/qr",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def ticket_qr(ticket_id: int, user: CurrentUser, db: DbSession):

    ticket = db.get(Ticket, ticket_id)
    if ticket is None or (ticket.order.user_id != user.id and user.role != Role.ADMIN):
        raise NotFoundError("Ticket not found")
    if ticket.status != TicketStatus.CONFIRMED:
        raise ConflictError("This ticket is no longer valid")
    return Response(generate_qr_png(ticket.code), media_type="image/png")
