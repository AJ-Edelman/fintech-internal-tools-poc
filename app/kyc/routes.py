"""Tool 2 routes: queue, customer review page, decision. Every route checks a permission."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.foundation import audit, customers, web
from app.foundation.auth import User, require
from app.foundation.errors import AppError
from app.foundation.web import page, tx

from . import workflow as kyc

router = APIRouter()
web.NAV.append(("/kyc/queue", "KYC queue", "kyc:review"))


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


@router.get("/kyc/queue", response_class=HTMLResponse)
def queue_page(request: Request, user: User = Depends(require("kyc:review"))):
    with tx(request) as conn:
        items = kyc.pending_queue(conn)
    return page(request, "kyc_queue.html", user, customers=items)


def _review(request, user, customer_id, status_code=200, error=None):
    with tx(request) as conn:
        # Shared detail view: unmasked only with pii:read, and then audited.
        customer = customers.get_customer(conn, customer_id, user)
        history = audit.history(conn, "customer", customer_id)
    return page(request, "kyc_review.html", user, status_code=status_code, customer=customer,
                history=history, error=error)


@router.get("/kyc/{customer_id}", response_class=HTMLResponse)
def review_page(request: Request, customer_id: int, user: User = Depends(require("kyc:review"))):
    return _review(request, user, customer_id)


@router.post("/kyc/{customer_id}/decision", response_class=HTMLResponse)
def decision_submit(request: Request, customer_id: int, decision: str = Form(""),
                    reason: str = Form(""), user: User = Depends(require("kyc:review"))):
    try:
        with tx(request) as conn:
            kyc.decide_kyc(conn, user, customer_id, decision, reason)
    except AppError as exc:
        if exc.status != 422:
            raise
        return _review(request, user, customer_id, status_code=422, error=exc.detail)
    return RedirectResponse("/kyc/queue", status_code=303)
