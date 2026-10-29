import getpass

from sqlalchemy import select

from core.database import SessionLocal
from core.security import hash_password
from models import Role, User, UserStatus


def main() -> None:
    email = input("Admin email: ").strip().lower()
    name = input("Full name: ").strip() or "Platform Admin"
    password = getpass.getpass("Password (min 8 chars): ")
    if len(password) < 8:
        raise SystemExit("Password too short")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email))
        if user:
            user.role, user.status = Role.ADMIN, UserStatus.ACTIVE
            user.hashed_password = hash_password(password)
            print(f"Promoted existing user {email} to admin")
        else:
            db.add(
                User(
                    email=email,
                    full_name=name,
                    hashed_password=hash_password(password),
                    role=Role.ADMIN,
                )
            )
            print(f"Created admin {email}")
        db.commit()


if __name__ == "__main__":
    main()
