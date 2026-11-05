"""Entry point of the KaasuPay loan portal.

Run with:  uvicorn app.main:app --reload
"""
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.deps import NotAuthenticated, get_optional_user
from app.models import User
from app.routers import auth, customer, staff
from app.templating import STATIC_DIR, render

app = FastAPI(title=settings.app_name)

# /static/... serves CSS. (Uploaded ID images will NOT live here — see CLAUDE.md.)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(auth.router)
app.include_router(customer.router)
app.include_router(staff.router)


@app.exception_handler(NotAuthenticated)
def redirect_to_login(request: Request, exc: NotAuthenticated):
    """Not logged in -> go to the login page (like a switch sending you to the login prompt)."""
    return RedirectResponse("/login", status_code=303)


@app.exception_handler(StarletteHTTPException)
def show_error_page(request: Request, exc: StarletteHTTPException):
    """403, 404, ... as a friendly HTML page (with the demo banner) instead of raw JSON."""
    return render(request, "error.html",
                  {"status_code": exc.status_code, "detail": exc.detail},
                  status_code=exc.status_code)


@app.get("/")
def home(request: Request, user: User | None = Depends(get_optional_user)):
    """The landing page."""
    return render(request, "home.html", {"user": user, "app_name": settings.app_name})


@app.get("/health")
def health():
    """Tiny JSON check that the server is up (handy for testing)."""
    return {"status": "ok"}
