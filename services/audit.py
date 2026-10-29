from sqlalchemy.orm import Session

from models import AuditLog, User


def log_action(
    db: Session,
    admin: User,
    action: str,
    target_type: str,
    target_id: int,
    details: dict | None = None,
) -> AuditLog:

    entry = AuditLog(
        admin_id=admin.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )
    db.add(entry)
    return entry
