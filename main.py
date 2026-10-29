import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from core.config import settings
from core.database import engine
from core.exceptions import TicketFlowError
from core.rate_limit import limiter
from models import Base
from routers import admin, auth, events, orders, seats, ticket_types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ticketflow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Event ticketing API: events, ticket inventory, seat selection, bookings, admin.",
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
