"""Background emails. They open their own DB session because the request session is closed."""

import logging
import smtplib
from email.message import EmailMessage

from core.config import settings
from core.database import SessionLocal
from models import Event, Order, TicketStatus, User
from services.qr import generate_qr_png

logger = logging.getLogger("ticketflow.email")


def _send(msg: EmailMessage) -> None:
    if not settings.smtp_host:
        logger.info("SMTP not configured; would send %r to %s", msg["Subject"], msg["To"])
        return
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except Exception:
        logger.exception("Failed to send email to %s", msg["To"])


def _base(to: str, subject: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    return msg


def send_ticket_email(order_id: int) -> None:
    with SessionLocal() as db:
        order = db.get(Order, order_id)
        if order is None:
            return
        user, event = db.get(User, order.user_id), db.get(Event, order.event_id)
        msg = _base(user.email, f"Your tickets for {event.name}")
        msg.set_content(
            f"Hi {user.full_name},\n\nYour payment for order #{order.id} was received. "
            f"Your QR tickets for {event.name} at {event.venue} are attached."
        )
        for ticket in order.tickets:
            if ticket.status == TicketStatus.CONFIRMED:
                msg.add_attachment(
                    generate_qr_png(ticket.code),
                    maintype="image",
                    subtype="png",
                    filename=f"ticket-{ticket.id}.png",
                )
    _send(msg)


def send_refund_email(order_id: int) -> None:
    with SessionLocal() as db:
        order = db.get(Order, order_id)
        if order is None:
            return
        user, event = db.get(User, order.user_id), db.get(Event, order.event_id)
        msg = _base(user.email, f"Refund for {event.name}")
        msg.set_content(
            f"Hi {user.full_name},\n\nOrder #{order.id} ({event.name}) was refunded "
            f"({order.total_amount} {settings.currency}). Its tickets are no longer valid."
        )
    _send(msg)
