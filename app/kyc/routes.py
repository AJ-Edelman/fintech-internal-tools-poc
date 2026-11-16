"""Tool 2 routes: queue, customer review page, decision. Every route checks a permission."""
from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.foundation import audit, customers, settings, web
from app.foundation.auth import User, require
from app.foundation.errors import AppError
from app.foundation.web import page, tx

from . import workflow as kyc

router = APIRouter()
web.NAV.insert(5, ("/kyc/queue", "KYC queue", "kyc:review", "Compliance"))


class KycDecisionBody(BaseModel):
    decision: str
    reason: str


@router.get("/api/kyc/queue")
def api_queue(request: Request, user: User = Depends(require("kyc:review"))):
    with tx(request) as conn:
        return {"items": kyc.pending_queue(conn)}


@router.post("/api/kyc/{customer_id}/decision")
def api_decide(request: Request, customer_id: int, body: KycDecisionBody,
               user: User = Depends(require("kyc:review"))):
    with tx(request) as conn:
        return kyc.decide_kyc(conn, user, customer_id, body.decision, body.reason)


def _reasons(conn) -> dict:
    return {"approve_reasons": settings.reason_options(conn, "reasons_kyc_approve"),
            "reject_reasons": settings.reason_options(conn, "reasons_kyc_reject")}


def _queue(request, user, q=None, status=None, sort=None, direction=None, page_no=1, page_size=25,
           status_code=200, error=None, done=None, done_id=None):
    with tx(request) as conn:
        result = customers.search_customers(conn, q, status or "pending" if status != "all" else None,
                                            sort, direction, page_no, page_size)
        reasons = _reasons(conn)
    return page(request, "kyc_queue.html", user, status_code=status_code, result=result,
                status=status or "pending", statuses=customers.KYC_STATUSES, error=error,
                done=done if done in ("approve", "reject") else None, done_id=done_id, **reasons)


@router.get("/kyc/queue", response_class=HTMLResponse)
def queue_page(request: Request, q: str | None = None, status: str | None = None,
               sort: str | None = None, dir: str | None = None,
               page_no: int = Query(1, ge=1, alias="page"), page_size: int = Query(25, ge=1, le=200),
               done: str | None = None, id: int | None = None,
               user: User = Depends(require("kyc:review"))):
    return _queue(request, user, q, status, sort, dir, page_no, page_size, done=done, done_id=id)


def _review(request, user, customer_id, status_code=200, error=None):
    with tx(request) as conn:
        # Shared detail view: unmasked only with pii:read, and then audited.
        customer = customers.get_customer(conn, customer_id, user)
        history = audit.history(conn, "customer", customer_id)
        reasons = _reasons(conn)
    return page(request, "kyc_review.html", user, status_code=status_code, customer=customer,
                history=history, error=error, **reasons)


@router.get("/kyc/{customer_id}", response_class=HTMLResponse)
def review_page(request: Request, customer_id: int, user: User = Depends(require("kyc:review"))):
    return _review(request, user, customer_id)


@router.post("/kyc/{customer_id}/decision", response_class=HTMLResponse)
def decision_submit(request: Request, customer_id: int, decision: str = Form(""),
                    reason: str = Form(""), reason_choice: str = Form(""), reason_other: str = Form(""),
                    source: str = Form(""), user: User = Depends(require("kyc:review"))):
    try:
        with tx(request) as conn:
            key = "reasons_kyc_reject" if decision == "reject" else "reasons_kyc_approve"
            chosen = settings.resolve_reason(conn, key, reason_choice, reason_other, reason)
            kyc.decide_kyc(conn, user, customer_id, decision, chosen)
    except AppError as exc:
        if exc.status != 422:
            raise
        if source == "queue":
            return _queue(request, user, status_code=422, error=f"Customer #{customer_id}: {exc.detail}")
        return _review(request, user, customer_id, status_code=422, error=exc.detail)
    return RedirectResponse(f"/kyc/queue?done={decision}&id={customer_id}", status_code=303)
