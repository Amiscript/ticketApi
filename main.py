import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from core.config import settings
from core.database import SessionLocal
from core.exceptions import TicketFlowError
from core.rate_limit import limiter
from routers import admin, auth, events, orders, seats, ticket_types
from services.orders import release_expired_reservations

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ticketflow")


def _release_expired() -> None:
    with SessionLocal() as db:
        count = release_expired_reservations(db)
        if count:
            logger.info("Released %d expired reservation(s)", count)


async def _expiry_loop() -> None:

    while True:
        try:
            await asyncio.to_thread(_release_expired)
        except Exception:
            logger.exception("Expiry job failed")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_expiry_loop()) if settings.run_expiry_task else None
    yield
    if task:
        task.cancel()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Event ticketing API: events, ticket inventory, seat selection, purchases, admin.",
    lifespan=lifespan,
    debug=settings.debug,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(TicketFlowError)
async def business_error_handler(request: Request, exc: TicketFlowError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(auth.router)
app.include_router(events.router)
app.include_router(ticket_types.router)
app.include_router(seats.router)
app.include_router(orders.router)
app.include_router(orders.tickets_router)
app.include_router(admin.router)


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}
