"""Connector admin routes and page (connector:read, connector:retry). Owner after stage 0: worker A."""
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text

from . import connectors, lists, web
from .auth import User, require
from .errors import AppError

router = APIRouter()
web.NAV.append(("/admin/connectors", "Outbound messages", "connector:read", "Admin"))

MESSAGE_LIST = lists.ListSpec(
    name="Outbound messages", permission="connector:read", source="connector_message m",
    columns=(
        lists.Column("id", "Message", "m.id", sortable=True),
        lists.Column("connector", "Connector", "m.connector", searchable=True, sortable=True),
        lists.Column("kind", "Kind", "m.kind", searchable=True, sortable=True),
        lists.Column("entity", "Record type", "m.entity", searchable=True, sortable=True),
        lists.Column("entity_id", "Record", "m.entity_id", searchable=True, sortable=True),
        lists.Column("status", "Status", "m.status", sortable=True, kind="status"),
        lists.Column("attempts", "Attempts", "m.attempts", sortable=True),
        lists.Column("last_error", "Last error", "m.last_error"),
        lists.Column("created_at", "Created", "m.created_at", sortable=True, kind="date"),
    ),
    filters=(lists.Filter("status", "Status", "m.status",
                          tuple((s, s.capitalize()) for s in connectors.STATUSES)),),
    default_sort="id", default_dir="desc",
)


class RetryBody(BaseModel):
    reason: str


@router.get("/api/connectors/messages")
def api_messages(request: Request, status: str | None = None, page: int = Query(1, ge=1),
                 page_size: int = Query(50, ge=1, le=200),
                 user: User = Depends(require("connector:read"))):
    if status and status not in connectors.STATUSES:
        raise AppError(422, "status must be one of " + ", ".join(connectors.STATUSES))
    where = " WHERE status = :status" if status else ""
    params = {"status": status, "limit": page_size, "offset": (page - 1) * page_size}
    with web.tx(request) as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM connector_message" + where), params).scalar_one()
        items = [dict(r) for r in conn.execute(text(
            "SELECT * FROM connector_message" + where + " ORDER BY id LIMIT :limit OFFSET :offset"
        ), params).mappings()]
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": (total + page_size - 1) // page_size}


@router.post("/api/connectors/messages/{id}/retry")
def api_retry(request: Request, id: int, body: RetryBody,
              user: User = Depends(require("connector:retry"))):
    return connectors.retry(request.app.state.engine, user, id, body.reason)


@router.get("/admin/connectors", response_class=HTMLResponse)
def messages_page(request: Request, user: User = Depends(require("connector:read"))):
    with web.tx(request) as conn:
        result = lists.run(conn, MESSAGE_LIST, user, request.query_params)
    return lists.render(request, user, MESSAGE_LIST, result, template="connector_detail.html")


@router.post("/admin/connectors/{id}/retry", response_class=HTMLResponse)
def retry_submit(request: Request, id: int, reason: str = Form(""),
                 user: User = Depends(require("connector:retry"))):
    connectors.retry(request.app.state.engine, user, id, reason)
    return RedirectResponse("/admin/connectors", status_code=303)
