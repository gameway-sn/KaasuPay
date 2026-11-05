"""The Jinja2 template engine, shared by main.py and all routers."""
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.services.money import format_inr

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

templates = Jinja2Templates(directory=APP_DIR / "templates")

# In templates: {{ loan.emi_paise | inr }}  ->  ₹9,168.00
templates.env.filters["inr"] = format_inr


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200):
    """Shortcut: render a template into an HTML response."""
    return templates.TemplateResponse(request, name, context or {}, status_code=status_code)
