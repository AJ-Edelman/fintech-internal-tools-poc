"""Tool 1 routes: pages and API. Every route checks a permission."""
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, StrictInt

from app.foundation import audit, customers, lists, scope, settings
from app.foundation.auth import User, require
from app.foundation.errors import AppError
from app.foundation.web import page, to_cents, tx

from . import workflow as refunds

router = APIRouter()
MAX_PAGE_SIZE = 200


from dataclasses import replace

from app.foundation.lists import Column, Filter, ListSpec

REFUND_LIST = lists.register(ListSpec(
    name="refunds", permission="refund:read", source=refunds._REFUND_FROM,
    columns=(Column("id", "ID", "r.id", searchable=True, sortable=True),
             Column("charge", "Charge", "r.charge_id", searchable=True, sortable=True),
             Column("customer", "Customer", "cu.name", searchable=True, sortable=True),
             Column("amount", "Amount", "r.amount_cents", sortable=True, kind="money"),
             Column("status", "Status", "r.status", sortable=True, kind="status"),
             Column("requested_by", "Requested by", "r.requested_by", searchable=True, sortable=True),
             Column("decided_by", "Decided by", "r.decided_by", searchable=True, sortable=True),
             Column("reason", "Reason", "r.reason", searchable=True),
             Column("created_at", "Created", "r.created_at", sortable=True, kind="date")),
    filters=(Filter("status", "Status", "r.status", tuple((s, s) for s in refunds.STATUSES)),),
    customer_id_expr="ch.customer_id", tiebreak="r.id", extra={"select": refunds._REFUND_SELECT}))

REFUND_QUEUE = lists.register(replace(
    REFUND_LIST, name="refund_queue", permission="refund:approve", filters=(),
    where=(f"r.status = '{refunds.PENDING}'",), waiting_since="r.created_at"))


def list_refunds(conn, user, spec, status=None, page=1, page_size=25, q=None, sort=None, direction=None):
    params = {"status": status, "page": page, "page_size": page_size, "q": q, "sort": sort, "dir": direction}
    result = lists.run(conn, spec, user, {k: str(v) for k, v in params.items() if v not in (None, "")})
    result["status"] = status if spec is REFUND_LIST else refunds.PENDING
    return result


class RefundBody(BaseModel):
    charge_id: StrictInt
    amount_cents: StrictInt
    reason: str


class DecisionBody(BaseModel):
    reason: str


@router.get("/api/refunds")
def api_list(request: Request, status: str | None = None, page: int = Query(1, ge=1),
             page_size: int = Query(50, ge=1, le=MAX_PAGE_SIZE), q: str | None = None,
             sort: str | None = None, dir: str | None = None,
             user: User = Depends(require("refund:read"))):
    with tx(request) as conn:
        return list_refunds(conn, user, REFUND_LIST, status or None, page, page_size, q, sort, dir)


@router.post("/api/refunds", status_code=201)
def api_create(request: Request, body: RefundBody, user: User = Depends(require("refund:create"))):
    with tx(request) as conn:
        return refunds.request_refund(conn, user, body.charge_id, body.amount_cents, body.reason)


@router.get("/api/refunds/{refund_id}")
def api_detail(request: Request, refund_id: int, user: User = Depends(require("refund:read"))):
    with tx(request) as conn:
        refund = refunds.get_refund(conn, refund_id)
        scope.check_customer(conn, user, "refund:read", refund["customer_id"])
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
def list_page(request: Request, status: str | None = None, q: str | None = None,
              sort: str | None = None, dir: str | None = None,
              page_no: int = Query(1, ge=1, alias="page"),
              page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
              user: User = Depends(require("refund:read"))):
    with tx(request) as conn:
        result = list_refunds(conn, user, REFUND_LIST, status or None, page_no, page_size, q, sort, dir)
    return lists.render(request, user, REFUND_LIST, result, "refunds_list.html", statuses=refunds.STATUSES)


def _picker(request, user, q=None, show=None, sort=None, direction=None, page_no=1, page_size=25):
    """Step 1 of a request: find the charge in a searchable, sortable table."""
    with tx(request) as conn:
        result = customers.search_charges(conn, q, None, show != "all", None, sort, direction,
                                          page_no, page_size, user=user)
        rules = settings.refund_rules(conn)
    return lists.render(request, user, customers.CHARGE_LIST, result, "charges.html", statuses=customers.KYC_STATUSES,
                picker=True, show=show or "refundable", rules=rules)


def _form(request, user, charge_id, status_code=200, error=None, values=None):
    with tx(request) as conn:
        charge = customers.get_charge(conn, charge_id)
        if charge is not None:
            scope.check_customer(conn, user, "refund:create", charge["customer_id"])
        reasons = settings.reason_options(conn, "reasons_refund_request")
        limit = settings.get_auto_approve_limit(conn)
        rules = settings.refund_rules(conn)
    if charge is None:
        raise AppError(422, f"charge {charge_id} does not exist")
    return page(request, "refund_form.html", user, status_code=status_code, charge=charge,
                reasons=reasons, limit_cents=limit, rules=rules, error=error, values=values or {})


@router.get("/refunds/new", response_class=HTMLResponse)
def new_page(request: Request, charge_id: int | None = None, q: str | None = None,
             show: str | None = None, sort: str | None = None, dir: str | None = None,
             page_no: int = Query(1, ge=1, alias="page"),
             page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
             user: User = Depends(require("refund:create"))):
    if charge_id is None:
        return _picker(request, user, q, show, sort, dir, page_no, page_size)
    return _form(request, user, charge_id)


@router.post("/refunds/new", response_class=HTMLResponse)
def new_submit(request: Request, charge_id: str = Form(""), amount: str = Form(""),
               reason: str = Form(""), reason_choice: str = Form(""), reason_other: str = Form(""),
               user: User = Depends(require("refund:create"))):
    values = {"charge_id": charge_id, "amount": amount, "reason_choice": reason_choice,
              "reason_other": reason_other or reason}
    try:
        charge = int(charge_id)
    except ValueError:
        raise AppError(422, "choose a charge")
    try:
        with tx(request) as conn:
            chosen = settings.resolve_reason(conn, "reasons_refund_request", reason_choice,
                                             reason_other, reason)
            refund = refunds.request_refund(conn, user, charge, to_cents(amount), chosen)
    except AppError as exc:
        if exc.status != 422:
            raise
        return _form(request, user, charge, status_code=422, error=exc.detail, values=values)
    return RedirectResponse(f"/refunds/{refund['id']}", status_code=303)


def _queue(request, user, q=None, sort=None, direction=None, page_no=1, page_size=25,
           status_code=200, error=None, done=None, done_id=None):
    with tx(request) as conn:
        result = list_refunds(conn, user, REFUND_QUEUE, None, page_no, page_size, q, sort, direction)
        approve = settings.reason_options(conn, "reasons_refund_approve")
        reject = settings.reason_options(conn, "reasons_refund_reject")
    return lists.render(request, user, REFUND_QUEUE, result, "refund_queue.html", status_code=status_code,
                approve_reasons=approve, reject_reasons=reject, error=error,
                done=done if done in ("approve", "reject") else None, done_id=done_id)


@router.get("/refunds/queue", response_class=HTMLResponse)
def queue_page(request: Request, q: str | None = None, sort: str | None = None, dir: str | None = None,
               page_no: int = Query(1, ge=1, alias="page"),
               page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE),
               done: str | None = None, id: int | None = None,
               user: User = Depends(require("refund:approve"))):
    return _queue(request, user, q, sort, dir, page_no, page_size, done=done, done_id=id)


def _detail(request, user, refund_id, status_code=200, error=None):
    with tx(request) as conn:
        refund = refunds.get_refund(conn, refund_id)
        scope.check_customer(conn, user, "refund:read", refund["customer_id"])
        history = audit.history(conn, "refund", refund_id)
        approve = settings.reason_options(conn, "reasons_refund_approve")
        reject = settings.reason_options(conn, "reasons_refund_reject")
    return page(request, "refund_detail.html", user, status_code=status_code, refund=refund,
                history=history, approve_reasons=approve, reject_reasons=reject, error=error)


@router.get("/refunds/{refund_id}", response_class=HTMLResponse)
def detail_page(request: Request, refund_id: int, user: User = Depends(require("refund:read"))):
    return _detail(request, user, refund_id)


@router.post("/refunds/{refund_id}/decision", response_class=HTMLResponse)
def decision_submit(request: Request, refund_id: int, decision: str = Form(""),
                    reason: str = Form(""), reason_choice: str = Form(""), reason_other: str = Form(""),
                    source: str = Form(""), user: User = Depends(require("refund:approve"))):
    try:
        with tx(request) as conn:
            key = "reasons_refund_reject" if decision == "reject" else "reasons_refund_approve"
            chosen = settings.resolve_reason(conn, key, reason_choice, reason_other, reason)
            refunds.decide_refund(conn, user, refund_id, decision, chosen)
    except AppError as exc:
        if exc.status != 422:
            raise
        if source == "queue":
            return _queue(request, user, status_code=422, error=f"Refund #{refund_id}: {exc.detail}")
        return _detail(request, user, refund_id, status_code=422, error=exc.detail)
    if source == "queue":
        return RedirectResponse(f"/refunds/queue?done={decision}&id={refund_id}", status_code=303)
    return RedirectResponse(f"/refunds/{refund_id}", status_code=303)
