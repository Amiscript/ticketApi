from sqlalchemy.orm import Session

from core.exceptions import ForbiddenError, NotFoundError
from models import Event, EventStatus, Role, User


def get_owned_event(db: Session, event_id: int, user: User) -> Event:
    """Event the user may modify: its organizer (admins moderate via /admin instead)."""
    event = db.get(Event, event_id)
    if event is None:
        raise NotFoundError("Event not found")
    if event.organizer_id != user.id:
        raise ForbiddenError("You do not own this event")
    return event


def get_visible_event(db: Session, event_id: int, user: User | None) -> Event:
    """Approved events are public. Anything else is only visible to its owner or an admin.

    Hidden events return 404 (not 403) so their existence is not leaked.
    """
    event = db.get(Event, event_id)
    if event is None:
        raise NotFoundError("Event not found")
    if event.status == EventStatus.APPROVED:
        return event
    if user is not None and (user.role == Role.ADMIN or event.organizer_id == user.id):
        return event
    raise NotFoundError("Event not found")
