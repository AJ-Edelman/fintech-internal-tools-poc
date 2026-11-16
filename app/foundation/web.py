"""Shared web plumbing: app factory pieces, templates, error rendering, foundation routes."""
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, StrictInt

from . import audit, auth, customers, settings
from .auth import User, require
from .errors import AppError
from .permissions import ALL_PERMISSIONS

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
templates.env.filters["dollars"] = lambda cents: f"${cents / 100:,.2f}"

# Links shown in the nav, each only to callers holding its permission.
NAV: list[tuple[str, str, str]] = [
    ("/refunds", "Refunds", "refund:read"),
    ("/refunds/new", "Request refund", "refund:create"),
    ("/refunds/queue", "Approval queue", "refund:approve"),
    ("/customers", "Customers", "customer:read"),
    ("/admin/settings", "Settings", "settings:write"),
    ("/admin/access-review", "Access review", "access_review:read"),
    ("/admin/audit", "Audit log", "audit:read"),
]


def is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def page(request: Request, name: str, user: User | None, status_code: int = 200, **ctx):
    nav = [(href, label) for href, label, perm in NAV if user and perm in user.permissions]
    return templates.TemplateResponse(
        request, name, {"user": user, "nav": nav, **ctx}, status_code=status_code
    )


def tx(request: Request):
    return request.app.state.engine.begin()


def install_error_handlers(app) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):
        if is_api(request):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status)
        if exc.status == 401:
            return RedirectResponse("/login?next=" + quote(request.url.path), status_code=303)
        user = getattr(request.state, "user", None)
        return page(request, "error.html", user, status_code=exc.status,
                    status=exc.status, detail=exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in exc.errors()
        )
        if is_api(request):
            return JSONResponse({"detail": detail}, status_code=422)
        user = getattr(request.state, "user", None)
        return page(request, "error.html", user, status_code=422, status=422, detail=detail)


router = APIRouter()


def _safe_next(target: str | None) -> str:
    return target if target and target.startswith("/") and not target.startswith("//") else "/"


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    return page(request, "login.html", None, next=_safe_next(next), error=None)


@router.post("/login")
def login_submit(request: Request, username: str = Form(""), password: str = Form(""),
                 next: str = Form("/")):
    with tx(request) as conn:
        token = auth.login(conn, username, password)
    if token is None:
        return page(request, "login.html", None, status_code=401, next=_safe_next(next),
                    error="Wrong username or password")
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax")
    return response


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/api/login")
def api_login(request: Request, body: LoginBody):
    with tx(request) as conn:
        token = auth.login(conn, body.username, body.password)
    if token is None:
        raise AppError(401, "wrong username or password")
    response = JSONResponse({"username": body.username})
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax")
    return response


@router.get("/")
def landing(request: Request, user: User = Depends(require(*sorted(ALL_PERMISSIONS)))):
    for href, _label, perm in NAV:
        if perm in user.permissions:
            return RedirectResponse(href, status_code=303)
    raise AppError(403, "permission denied")


# --- customers (shared model) -------------------------------------------------

@router.get("/api/customers")
def api_customers(request: Request, user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        return {"items": customers.list_customers(conn)}


@router.get("/api/customers/{customer_id}")
def api_customer(request: Request, customer_id: int, user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        return customers.get_customer(conn, customer_id, user)


@router.get("/api/charges")
def api_charges(request: Request, customer_id: int | None = None,
                user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        return {"items": customers.list_charges(conn, customer_id)}


@router.get("/customers", response_class=HTMLResponse)
def customers_page(request: Request, user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        items = customers.list_customers(conn)
    return page(request, "customers.html", user, customers=items)


@router.get("/customers/{customer_id}", response_class=HTMLResponse)
def customer_page(request: Request, customer_id: int, user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        customer = customers.get_customer(conn, customer_id, user)
        charges = customers.list_charges(conn, customer_id)
    return page(request, "customer_detail.html", user, customer=customer, charges=charges)


# --- admin: settings, access review, audit ---------------------------------------

class LimitBody(BaseModel):
    value_cents: StrictInt
    reason: str


@router.get("/api/settings/auto-approve-limit")
def api_get_limit(request: Request, user: User = Depends(require("settings:write"))):
    with tx(request) as conn:
        return {"value_cents": settings.get_auto_approve_limit(conn),
                "max_cents": settings.AUTO_APPROVE_LIMIT_MAX_CENTS}


@router.put("/api/settings/auto-approve-limit")
def api_set_limit(request: Request, body: LimitBody, user: User = Depends(require("settings:write"))):
    with tx(request) as conn:
        value = settings.set_auto_approve_limit(conn, user, body.value_cents, body.reason)
    return {"value_cents": value, "max_cents": settings.AUTO_APPROVE_LIMIT_MAX_CENTS}


def _settings_page(request, user, status_code=200, error=None, saved=False):
    with tx(request) as conn:
        value = settings.get_auto_approve_limit(conn)
    return page(request, "settings.html", user, status_code=status_code, value_cents=value,
                max_cents=settings.AUTO_APPROVE_LIMIT_MAX_CENTS, error=error, saved=saved)


@router.get("/admin/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: User = Depends(require("settings:write"))):
    return _settings_page(request, user)


@router.post("/admin/settings", response_class=HTMLResponse)
def settings_submit(request: Request, value_cents: str = Form(""), reason: str = Form(""),
                    user: User = Depends(require("settings:write"))):
    try:
        try:
            value = int(value_cents.strip())
        except ValueError:
            raise AppError(422, "limit must be a whole number of cents")
        with tx(request) as conn:
            settings.set_auto_approve_limit(conn, user, value, reason)
    except AppError as exc:
        if exc.status != 422:
            raise
        return _settings_page(request, user, status_code=422, error=exc.detail)
    return _settings_page(request, user, saved=True)


@router.get("/api/access-review")
def api_access_review(request: Request, user: User = Depends(require("access_review:read"))):
    with tx(request) as conn:
        return {"assignments": customers.role_assignments(conn)}


@router.get("/admin/access-review", response_class=HTMLResponse)
def access_review_page(request: Request, user: User = Depends(require("access_review:read"))):
    with tx(request) as conn:
        rows = customers.role_assignments(conn)
    return page(request, "access_review.html", user, assignments=rows)


@router.get("/api/audit")
def api_audit(request: Request, entity: str | None = None, entity_id: str | None = None,
              limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              user: User = Depends(require("audit:read"))):
    with tx(request) as conn:
        if entity and entity_id:
            return {"items": audit.history(conn, entity, entity_id)}
        return {"items": audit.recent(conn, limit, offset)}


@router.get("/admin/audit", response_class=HTMLResponse)
def audit_page(request: Request, user: User = Depends(require("audit:read"))):
    with tx(request) as conn:
        events = audit.recent(conn, 200)
    return page(request, "audit.html", user, events=events)
