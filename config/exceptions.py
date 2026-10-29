class TicketFlowError(Exception):
    """Base class for business-rule errors. The handler in main.py turns them into JSON."""

    status_code = 400

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


class BadRequestError(TicketFlowError):
    status_code = 400


class ForbiddenError(TicketFlowError):
    status_code = 403


class NotFoundError(TicketFlowError):
    status_code = 404


class ConflictError(TicketFlowError):
    status_code = 409
