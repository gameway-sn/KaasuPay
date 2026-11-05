"""The Jinja2 template engine, shared by main.py and all routers."""
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

templates = Jinja2Templates(directory=APP_DIR / "templates")


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200):
    """Shortcut: render a template into an HTML response."""
    return templates.TemplateResponse(request, name, context or {}, status_code=status_code)
