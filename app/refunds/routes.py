"""Tool 1 routes: pages and API. Every route checks a permission."""
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, StrictInt

from app.foundation import audit, customers
from app.foundation.auth import User, require
from app.foundation.errors import AppError
from app.foundation.web import page, tx

from . import workflow as refunds

router = APIRouter()
MAX_PAGE_SIZE = 200


class RefundBody(BaseModel):
    charge_id: StrictInt
    amount_cents: StrictInt
    reason: str


class DecisionBody(BaseModel):
    reason: str


@router.get("/api/refunds")
def api_list(request: Request, status: str | None = None, page: int = Query(1, ge=1),
             page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
             user: User = Depends(require("refund:read"))):
    with tx(request) as conn:
        return refunds.list_refunds(conn, status or None, page, page_size)


@router.post("/api/refunds", status_code=201)
def api_create(request: Request, body: RefundBody, user: User = Depends(require("refund:create"))):
    with tx(request) as conn:
        return refunds.request_refund(conn, user, body.charge_id, body.amount_cents, body.reason)


@router.get("/api/refunds/{refund_id}")
def api_detail(request: Request, refund_id: int, user: User = Depends(require("refund:read"))):
    with tx(request) as conn:
        refund = refunds.get_refund(conn, refund_id)
        refund["history"] = audit.history(conn, "refund", refund_id)
        return refund


@router.post("/api/refunds/{refund_id}/approve")
def api_approve(request: Request, refund_id: int, body: DecisionBody,
                user: User = Depends(require("refund:approve"))):
    with tx(request) as conn:
        return refunds.decide_refund(conn, user, refund_id, "approve", body.reason)


@router.post("/api/refunds/{refund_id}/reject")
def api_reject(request: Request, refund_id: int, body: DecisionBody,
               user: User = Depends(require("refund:approve"))):
    with tx(request) as conn:
        return refunds.decide_refund(conn, user, refund_id, "reject", body.reason)


# --- pages ------------------------------------------------------------------------

@router.get("/refunds", response_class=HTMLResponse)
def list_page(request: Request, status: str | None = None, page_no: int = Query(1, ge=1, alias="page"),
              page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
              user: User = Depends(require("refund:read"))):
    with tx(request) as conn:
        result = refunds.list_refunds(conn, status or None, page_no, page_size)
    pages = max(1, -(-result["total"] // page_size))
    return page(request, "refunds_list.html", user, result=result, pages=pages,
                statuses=refunds.STATUSES)


def _form(request, user, status_code=200, error=None, values=None):
    with tx(request) as conn:
        charges = customers.list_charges(conn)
    return page(request, "refund_form.html", user, status_code=status_code, charges=charges,
                error=error, values=values or {})


def _to_cents(amount: str) -> int:
    try:
        value = Decimal(amount.strip().replace("$", "").replace(",", ""))
    except (InvalidOperation, AttributeError):
        raise AppError(422, "amount must be a number of dollars, e.g. 12.34")
    if not value.is_finite():
        raise AppError(422, "amount must be a number of dollars, e.g. 12.34")
    cents = value * 100
    if cents != cents.to_integral_value():
        raise AppError(422, "amount cannot have fractions of a cent")
    return int(cents)


@router.get("/refunds/new", response_class=HTMLResponse)
def new_page(request: Request, user: User = Depends(require("refund:create"))):
    return _form(request, user)


@router.post("/refunds/new", response_class=HTMLResponse)
def new_submit(request: Request, charge_id: str = Form(""), amount: str = Form(""),
               reason: str = Form(""), user: User = Depends(require("refund:create"))):
    values = {"charge_id": charge_id, "amount": amount, "reason": reason}
    try:
        try:
            charge = int(charge_id)
        except ValueError:
            raise AppError(422, "choose a charge")
        with tx(request) as conn:
            refund = refunds.request_refund(conn, user, charge, _to_cents(amount), reason)
    except AppError as exc:
        if exc.status != 422:
            raise
        return _form(request, user, status_code=422, error=exc.detail, values=values)
    return RedirectResponse(f"/refunds/{refund['id']}", status_code=303)


@router.get("/refunds/queue", response_class=HTMLResponse)
def queue_page(request: Request, page_no: int = Query(1, ge=1, alias="page"),
               user: User = Depends(require("refund:approve"))):
    with tx(request) as conn:
        result = refunds.list_refunds(conn, refunds.PENDING, page_no, 25)
    pages = max(1, -(-result["total"] // 25))
    return page(request, "refund_queue.html", user, result=result, pages=pages)


@router.get("/refunds/{refund_id}", response_class=HTMLResponse)
def detail_page(request: Request, refund_id: int, user: User = Depends(require("refund:read"))):
    with tx(request) as conn:
        refund = refunds.get_refund(conn, refund_id)
        history = audit.history(conn, "refund", refund_id)
    return page(request, "refund_detail.html", user, refund=refund, history=history, error=None)


@router.post("/refunds/{refund_id}/decision", response_class=HTMLResponse)
def decision_submit(request: Request, refund_id: int, decision: str = Form(""),
                    reason: str = Form(""), user: User = Depends(require("refund:approve"))):
    try:
        with tx(request) as conn:
            refunds.decide_refund(conn, user, refund_id, decision, reason)
    except AppError as exc:
        if exc.status != 422:
            raise
        with tx(request) as conn:
            refund = refunds.get_refund(conn, refund_id)
            history = audit.history(conn, "refund", refund_id)
        return page(request, "refund_detail.html", user, status_code=422, refund=refund,
                    history=history, error=exc.detail)
    return RedirectResponse(f"/refunds/{refund_id}", status_code=303)
