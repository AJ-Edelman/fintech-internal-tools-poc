"""Tool 3 routes: built from the shared foundation (lists, workflow, scope, connectors, pages)."""
from dataclasses import replace

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, StrictInt

from app.foundation import audit, connectors, customers, lists, scope, web
from app.foundation.auth import User, require
from app.foundation.errors import AppError
from app.foundation.lists import Column, Filter, ListSpec
from app.foundation.web import page, to_cents, tx

from . import workflow as limits

router = APIRouter()
web.NAV.extend([
    ("/limits", "Limit overrides", "limit:read", "Limits"),
    ("/limits/new", "Request limit", "limit:request", "Limits"),
    ("/limits/queue", "Limit queue", "limit:approve", "Limits"),
])

LIMIT_LIST = lists.register(ListSpec(
    name="limit_overrides", permission="limit:read", source=limits.LIMIT_FROM,
    columns=(Column("id", "ID", "lo.id", searchable=True, sortable=True),
             Column("customer", "Customer", "cu.name", searchable=True, sortable=True),
             Column("current", "Current limit", "lo.current_limit_cents", sortable=True, kind="money"),
             Column("requested", "Requested limit", "lo.requested_limit_cents", sortable=True, kind="money"),
             Column("status", "Status", "lo.status", sortable=True, kind="status"),
             Column("requested_by", "Requested by", "lo.requested_by", searchable=True, sortable=True),
             Column("decided_by", "Decided by", "lo.decided_by", searchable=True, sortable=True),
             Column("reason", "Reason", "lo.reason", searchable=True),
             Column("created_at", "Created", "lo.created_at", sortable=True, kind="date")),
    filters=(Filter("status", "Status", "lo.status", tuple((s, s) for s in limits.STATUSES)),),
    customer_id_expr="lo.customer_id", tiebreak="lo.id", extra={"select": limits.LIMIT_SELECT}))

LIMIT_QUEUE = lists.register(replace(
    LIMIT_LIST, name="limit_queue", permission="limit:approve", filters=(),
    where=(f"lo.status = '{limits.PENDING}'",), waiting_since="lo.created_at"))


def _params(**kw) -> dict:
    return {k: str(v) for k, v in kw.items() if v not in (None, "")}


class LimitRequestBody(BaseModel):
    customer_id: StrictInt
    requested_limit_cents: StrictInt
    reason: str


class DecisionBody(BaseModel):
    reason: str


def _detail(conn, user, override_id: int, permission: str) -> dict:
    row = limits.get_override(conn, override_id)
    scope.check_customer(conn, user, permission, row["customer_id"])
    return row


@router.get("/api/limits")
def api_list(request: Request, status: str | None = None, q: str | None = None, sort: str | None = None,
             dir: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
             user: User = Depends(require("limit:read"))):
    with tx(request) as conn:
        result = lists.run(conn, LIMIT_LIST, user, _params(status=status, q=q, sort=sort, dir=dir,
                                                           page=page, page_size=page_size))
    return {"items": result["items"], "total": result["total"], "page": result["page"],
            "page_size": result["page_size"]}


@router.post("/api/limits", status_code=201)
def api_create(request: Request, body: LimitRequestBody, user: User = Depends(require("limit:request"))):
    with tx(request) as conn:
        return limits.request_override(conn, user, body.customer_id, body.requested_limit_cents, body.reason)


@router.get("/api/limits/{override_id}")
def api_detail(request: Request, override_id: int, user: User = Depends(require("limit:read"))):
    with tx(request) as conn:
        row = _detail(conn, user, override_id, "limit:read")
        row["history"] = audit.history(conn, "limit_override", override_id)
        row["message"] = connectors.latest_for(conn, "limit_override", override_id)
        return row


@router.post("/api/limits/{override_id}/approve")
def api_approve(request: Request, override_id: int, body: DecisionBody,
                user: User = Depends(require("limit:approve"))):
    with tx(request) as conn:
        return limits.decide_override(conn, user, override_id, "approve", body.reason)


@router.post("/api/limits/{override_id}/reject")
def api_reject(request: Request, override_id: int, body: DecisionBody,
               user: User = Depends(require("limit:approve"))):
    with tx(request) as conn:
        return limits.decide_override(conn, user, override_id, "reject", body.reason)


# --- pages ------------------------------------------------------------------------

@router.get("/limits", response_class=HTMLResponse)
def list_page(request: Request, status: str | None = None, q: str | None = None, sort: str | None = None,
              dir: str | None = None, page_no: int = Query(1, ge=1, alias="page"),
              page_size: int = Query(25, ge=1, le=200), user: User = Depends(require("limit:read"))):
    with tx(request) as conn:
        result = lists.run(conn, LIMIT_LIST, user, _params(status=status, q=q, sort=sort, dir=dir,
                                                           page=page_no, page_size=page_size))
    return lists.render(request, user, LIMIT_LIST, result, "limits_list.html", queue=False)


@router.get("/limits/queue", response_class=HTMLResponse)
def queue_page(request: Request, q: str | None = None, sort: str | None = None, dir: str | None = None,
               page_no: int = Query(1, ge=1, alias="page"), page_size: int = Query(25, ge=1, le=200),
               user: User = Depends(require("limit:approve"))):
    with tx(request) as conn:
        result = lists.run(conn, LIMIT_QUEUE, user, _params(q=q, sort=sort, dir=dir, page=page_no,
                                                            page_size=page_size))
    return lists.render(request, user, LIMIT_QUEUE, result, "limits_list.html", queue=True)


def _form(request, user, status_code=200, error=None, values=None):
    return page(request, "limit_form.html", user, status_code=status_code, error=error,
                values=values or {}, max_cents=limits.MAX_LIMIT_CENTS)


@router.get("/limits/new", response_class=HTMLResponse)
def new_page(request: Request, customer_id: int | None = None, user: User = Depends(require("limit:request"))):
    values = {}
    if customer_id is not None:
        with tx(request) as conn:
            customer = customers.get_customer(conn, customer_id, user)
        values = {"customer_id": customer_id, "customer": customer}
    return _form(request, user, values=values)


@router.post("/limits/new", response_class=HTMLResponse)
def new_submit(request: Request, customer_id: str = Form(""), amount: str = Form(""), reason: str = Form(""),
               user: User = Depends(require("limit:request"))):
    values = {"customer_id": customer_id, "amount": amount, "reason": reason}
    try:
        try:
            cid = int(customer_id)
        except ValueError:
            raise AppError(422, "enter a customer ID")
        with tx(request) as conn:
            row = limits.request_override(conn, user, cid, to_cents(amount, "new limit"), reason)
    except AppError as exc:
        if exc.status != 422:
            raise
        return _form(request, user, status_code=422, error=exc.detail, values=values)
    return RedirectResponse(f"/limits/{row['id']}", status_code=303)


def _detail_page(request, user, override_id, status_code=200, error=None):
    with tx(request) as conn:
        row = _detail(conn, user, override_id, "limit:read")
        history = audit.history(conn, "limit_override", override_id)
        message = connectors.latest_for(conn, "limit_override", override_id)
    return page(request, "limit_detail.html", user, status_code=status_code, item=row, history=history,
                message=message, error=error)


@router.get("/limits/{override_id}", response_class=HTMLResponse)
def detail_page(request: Request, override_id: int, user: User = Depends(require("limit:read"))):
    return _detail_page(request, user, override_id)


@router.post("/limits/{override_id}/decision", response_class=HTMLResponse)
def decision_submit(request: Request, override_id: int, decision: str = Form(""), reason: str = Form(""),
                    user: User = Depends(require("limit:approve"))):
    try:
        with tx(request) as conn:
            limits.decide_override(conn, user, override_id, decision, reason)
    except AppError as exc:
        if exc.status != 422:
            raise
        return _detail_page(request, user, override_id, status_code=422, error=exc.detail)
    return RedirectResponse(f"/limits/{override_id}", status_code=303)
