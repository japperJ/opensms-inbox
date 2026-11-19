"""OpenSMS Inbox: a small web inbox for OpenSMS webhooks."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import (
    delete_message,
    get_message,
    init_db,
    insert_message,
    list_messages,
)
from app.security import require_auth, verify_signature

BASE_DIR = Path(__file__).resolve().parent
PAGE_SIZE = 50


@dataclass
class Settings:
    db_path: str
    secret: str
    user: str
    password: str
    title: str


def load_settings() -> Settings:
    return Settings(
        db_path=os.environ.get("OPENMS_INBOX_DB", "data/inbox.db"),
        secret=os.environ.get("OPENMS_INBOX_SECRET", ""),
        user=os.environ.get("OPENMS_INBOX_USER", ""),
        password=os.environ.get("OPENMS_INBOX_PASSWORD", ""),
        title=os.environ.get("OPENMS_INBOX_TITLE", "OpenSMS Inbox"),
    )


def pretty_time(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("T", " ").split("+")[0].split("Z")[0]


def page_context(request: Request, query: str, page: int) -> dict:
    settings = request.app.state.settings
    page = max(1, page)
    offset = (page - 1) * PAGE_SIZE
    messages, total = list_messages(
        settings.db_path, query=query, limit=PAGE_SIZE, offset=offset
    )
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    return {
        "messages": messages,
        "total": total,
        "query": query,
        "page": page,
        "pages": pages,
        "title": settings.title,
    }


def create_app() -> FastAPI:
    settings = load_settings()
    init_db(settings.db_path)

    app = FastAPI(title=settings.title, docs_url=None, redoc_url=None)
    app.state.settings = settings

    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    templates.env.filters["pretty_time"] = pretty_time
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")),
              name="static")

    @app.post("/hook")
    async def receive_webhook(request: Request):
        body = await request.body()
        if settings.secret and not verify_signature(
            settings.secret,
            body,
            request.headers.get("X-OpenSMS-Signature"),
        ):
            raise HTTPException(status_code=401, detail="Invalid signature")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")
        if not isinstance(payload, dict) or not isinstance(
            payload.get("event"), str
        ):
            raise HTTPException(status_code=400, detail="Missing event")
        inserted, _ = insert_message(settings.db_path, payload, body)
        return {"ok": True, "duplicate": not inserted}

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        q: str = "",
        page: int = 1,
        _=Depends(require_auth),
    ):
        context = page_context(request, q.strip(), page)
        return templates.TemplateResponse(
            request=request, name="index.html", context=context
        )

    @app.get("/partials/messages", response_class=HTMLResponse)
    def messages_partial(
        request: Request,
        q: str = "",
        page: int = 1,
        _=Depends(require_auth),
    ):
        context = page_context(request, q.strip(), page)
        return templates.TemplateResponse(
            request=request, name="partials/messages.html", context=context
        )

    @app.get("/messages/{message_id}", response_class=HTMLResponse)
    def message_detail(
        request: Request,
        message_id: int,
        _=Depends(require_auth),
    ):
        message = get_message(settings.db_path, message_id)
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        return templates.TemplateResponse(
            request=request,
            name="detail.html",
            context={"message": message, "title": settings.title},
        )

    @app.post("/messages/{message_id}/delete")
    def remove_message(message_id: int, _=Depends(require_auth)):
        delete_message(settings.db_path, message_id)
        return RedirectResponse(url="/", status_code=303)

    @app.get("/health")
    def health():
        return {"ok": True}

    return app
