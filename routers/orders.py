from fastapi import APIRouter, BackgroundTasks, Request, Response
from sqlalchemy import select

from core.config import settings
from core.exceptions import ConflictError, NotFoundError
from core.rate_limit import limiter
from dependencies import CurrentUser, DbSession
from models import Order, Role, Ticket, TicketStatus
from schemas.order import ConfirmPayment, OrderCreate, OrderOut, PaymentInit
from services import orders as order_service
from services.email import send_ticket_email
from services.qr import generate_qr_png

router = APIRouter(prefix="/orders", tags=["Orders"])
tickets_router = APIRouter(prefix="/tickets", tags=["Tickets"])


@router.post("", response_model=OrderOut, status_code=201)
@limiter.limit(settings.rate_limit_purchase)
def reserve(request: Request, data: OrderCreate, user: CurrentUser, db: DbSession):
    """Step 1 - RESERVE. Holds the tickets/seats for a few minutes while you pay."""
    return order_service.create_order(db, user, data)


@router.get("", response_model=list[OrderOut])
def my_orders(user: CurrentUser, db: DbSession):
    return db.scalars(
        select(Order).where(Order.user_id == user.id).order_by(Order.id.desc())
    ).all()


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, user: CurrentUser, db: DbSession):
    return order_service.get_order(db, order_id, user)


@router.post("/{order_id}/pay", response_model=PaymentInit)
def pay(order_id: int, user: CurrentUser, db: DbSession):
    """Step 2 - PAY. Starts a payment; send the customer to `authorization_url`."""
    order, session = order_service.start_payment(db, user, order_id)
    return PaymentInit(
        reference=session.reference,
        authorization_url=session.authorization_url,
        amount=order.total_amount,
        currency=settings.currency,
    )


@router.post("/{order_id}/confirm", response_model=OrderOut)
def confirm(
    order_id: int,
    data: ConfirmPayment,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: DbSession,
):
    """Step 3 - CONFIRM. Verifies payment, confirms tickets, emails QR codes in the background."""
    order, newly_paid = order_service.confirm_payment(
        db, user, order_id, data.reference
    )
    if newly_paid:
        background_tasks.add_task(send_ticket_email, order.id)
    return order


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel(order_id: int, user: CurrentUser, db: DbSession):
    return order_service.cancel_order(db, user, order_id)


@tickets_router.get(
    "/{ticket_id}/qr",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def ticket_qr(ticket_id: int, user: CurrentUser, db: DbSession):
    """PNG QR code for a confirmed ticket you own."""
    ticket = db.get(Ticket, ticket_id)
    if ticket is None or (ticket.order.user_id != user.id and user.role != Role.ADMIN):
        raise NotFoundError("Ticket not found")
    if ticket.status != TicketStatus.CONFIRMED:
        raise ConflictError("QR codes are only available for confirmed tickets")
    return Response(generate_qr_png(ticket.code), media_type="image/png")
