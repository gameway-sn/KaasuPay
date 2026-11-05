"""Writing audit events.

record(...) only ADDS the event to the session. It is saved by the same
db.commit() as the action itself, so an action and its audit line are saved
together or not at all.

The client's IP address is picked up by ClientIpMiddleware, so services can
log it without every function having to pass the request around.
"""
from contextvars import ContextVar

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.user import User

_client_ip: ContextVar[str | None] = ContextVar("client_ip", default=None)

# Categories for the audit viewer: label -> action prefix.
CATEGORIES = {
    "KYC (views, approvals)": "kyc.",
    "Loans": "loan.",
    "Payments (money)": "payment.",
    "Logins": "auth.",
    "Staff admin": "admin.",
    "Access denied (403)": "access.",
}


class ClientIpMiddleware:
    """Remembers the client's IP address for the length of one request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        token = _client_ip.set(client[0] if client else None)
        try:
            await self.app(scope, receive, send)
        finally:
            _client_ip.reset(token)


def record(
    db: Session,
    actor: User | None,
    action: str,
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    customer_id: int | None = None,
    detail: str = "",
) -> AuditEvent:
    event = AuditEvent(
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        customer_id=customer_id,
        detail=detail[:300],
        ip=_client_ip.get(),
    )
    db.add(event)
    return event
