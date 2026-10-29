# TicketFlow API

FastAPI + SQLAlchemy 2 + PostgreSQL ticketing backend.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # edit SECRET_KEY / DATABASE_URL
python -m scripts.init_db   # or set AUTO_CREATE_TABLES=true
python -m scripts.create_admin
uvicorn main:app --reload
```

Docs at http://localhost:8000/docs. Run tests with `pytest` (uses SQLite).

## Production notes
- `DEBUG=false` requires a real `SECRET_KEY` (>=32 chars) and `PAYMENT_PROVIDER=paystack`.
- Use Alembic migrations instead of `create_all`.
- Rate limiting uses in-memory storage by default; set `RATE_LIMIT_STORAGE_URI=redis://...` with multiple workers.
- With several workers the expiry loop runs in each; harmless (row locks use SKIP LOCKED) but set `RUN_EXPIRY_TASK=false` on all but one if you prefer.
