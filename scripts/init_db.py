"""Create all tables (dev convenience). Use Alembic migrations for production.

Run from the project root:  python -m scripts.init_db
"""

from core.database import engine
from models import Base


def main() -> None:
    Base.metadata.create_all(engine)
    print("Tables created")


if __name__ == "__main__":
    main()
