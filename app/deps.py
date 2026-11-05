"""Shared FastAPI dependencies: who is logged in, and are they allowed here?

require_role(...) is the app's ACL: every protected route lists the roles
that may use it, just like each VLAN's ACL lists what it may reach.
"""
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import COOKIE_NAME, read_access_token


class NotAuthenticated(Exception):
    """Raised when a page needs login. main.py turns it into a redirect to /login."""


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """The logged-in user, or None. Never raises."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    user_id = read_access_token(token)
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    return user


def get_current_user(user: User | None = Depends(get_optional_user)) -> User:
    """The logged-in user. If nobody is logged in, send them to /login."""
    if user is None:
        raise NotAuthenticated()
    return user


def require_role(*roles: str):
    """Build a dependency that lets in only the given roles.

    Usage:  user: User = Depends(require_role(Role.SUPPORT, Role.FINANCE))
    """

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your role is not allowed to open this page.")
        return user

    return checker
