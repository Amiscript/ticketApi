# TicketFlow API

FastAPI + SQLAlchemy 2 + PostgreSQL event-ticketing backend (no payments: bookings confirm instantly).

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

## Flow
1. Organizer creates an event, ticket types (and seats for seated events). Admin approves it.
2. Customer `POST /orders` with `items` (general admission) or `seat_ids` (seated). Tickets are confirmed
   immediately and emailed as QR codes. `GET /tickets/{id}/qr` returns the QR PNG.
3. Customer can `POST /orders/{id}/cancel` until the event starts; admins can cancel any order via
   `POST /admin/orders/{id}/cancel`. Cancelled tickets/seats go back on sale.

## Production notes
- `DEBUG=false` requires a real `SECRET_KEY` (>=32 chars).
- Use Alembic migrations instead of `create_all`.
- Rate limiting uses in-memory storage by default; set `RATE_LIMIT_STORAGE_URI=redis://...` with multiple workers.
- Prices are informational only (stored on tickets/orders, no money is processed).
