"""Shared web plumbing: app factory pieces, templates, error rendering, foundation routes."""
import os
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, StrictBool, StrictInt
from sqlalchemy import text

from datetime import datetime
from decimal import Decimal, InvalidOperation

from . import audit, auth, customers, lists, settings, users
from .auth import User, require
from .errors import AppError
from .listing import MAX_PAGE_SIZE
from .permissions import ALL_PERMISSIONS, ROLE_LABELS, ROLE_PERMISSIONS, role_label

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
templates.env.filters["dollars"] = lambda cents: f"${cents / 100:,.2f}"



def _when(value: str | None) -> str:
    """'2026-11-15T20:39:01.123Z' -> 'Nov 15, 2026, 8:39 PM UTC'."""
    if not value:
        return ""
    try:
        parsed = datetime.strptime(value.replace(" ", "T")[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return value
    return f"{parsed:%b} {parsed.day}, {parsed.year}, {parsed.hour % 12 or 12}:{parsed:%M %p} UTC"


def _day(value: str | None) -> str:
    return _when(value).rsplit(",", 1)[0] if value else ""


templates.env.filters["when"] = _when
templates.env.filters["day"] = _day
templates.env.filters["role_label"] = role_label
templates.env.filters["words"] = lambda value: str(value).replace("_", " ").capitalize()
templates.env.filters["describe"] = audit.describe
templates.env.filters["ucfirst"] = lambda value: value[:1].upper() + value[1:]


def demo_login_enabled() -> bool:
    return os.environ.get("LEDGERLINE_DEMO_LOGIN") == "1"


def to_cents(amount: str, what: str = "amount") -> int:
    """Parse dollars typed by a person ('1,250.50', '$12') into cents."""
    cleaned = (amount or "").strip().replace("$", "").replace(",", "")
    if not cleaned or not all(ch.isdigit() or ch == "." for ch in cleaned):
        raise AppError(422, f"{what} must be a number of dollars, e.g. 12.34")
    try:
        cents = Decimal(cleaned) * 100
    except InvalidOperation:
        raise AppError(422, f"{what} must be a number of dollars, e.g. 12.34")
    if cents != cents.to_integral_value():
        raise AppError(422, f"{what} cannot have fractions of a cent")
    return int(cents)


# Links shown in the nav, each only to callers holding its permission: (href, label, permission, section).
NAV: list[tuple[str, str, str, str]] = [
    ("/refunds", "Refunds", "refund:read", "Refunds"),
    ("/refunds/new", "Request refund", "refund:create", "Refunds"),
    ("/refunds/queue", "Approval queue", "refund:approve", "Refunds"),
    ("/customers", "Customers", "customer:read", "Customers"),
    ("/charges", "Charges", "customer:read", "Customers"),
    ("/admin/settings", "Settings", "settings:write", "Admin"),
    ("/admin/access-review", "Users & access", "access_review:read", "Admin"),
    ("/admin/audit", "Audit log", "audit:read", "Admin"),
]


def is_api(request: Request) -> bool:
    return request.url.path.startswith("/api/")


def _qs(request: Request, **changes) -> str:
    """The current query string with `changes` applied; any change but `page` goes back to page 1."""
    params = dict(request.query_params)
    if "page" not in changes:
        params.pop("page", None)
    for key in ("done", "id"):
        params.pop(key, None)
    for key, value in changes.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = str(value)
    return "?" + urlencode(params)


def page(request: Request, name: str, user: User | None, status_code: int = 200, **ctx):
    visible = [entry for entry in NAV if user and entry[2] in user.permissions]
    path = request.url.path
    active = max((e[0] for e in visible if path == e[0] or path.startswith(e[0] + "/")),
                 key=len, default=None)
    sections: dict[str, list] = {}
    for href, label, _perm, section in visible:
        sections.setdefault(section, []).append((href, label, href == active))
    return templates.TemplateResponse(
        request, name,
        {"user": user, "nav": sections, "qs": lambda **changes: _qs(request, **changes),
         **ctx, "demo_login": demo_login_enabled()},
        status_code=status_code,
    )


def _demo_accounts(request: Request) -> list[tuple[str, list[dict[str, str]]]]:
    from app.seed import DEMO_USERS

    group_by_permission = {
        "refund:read": "Refunds",
        "kyc:review": "KYC review",
        "limit:read": "Account limits",
        "user:manage": "Admin",
    }
    groups = {label: [] for label in ("Refunds", "KYC review", "Account limits", "Admin")}
    with request.app.state.engine.begin() as conn:
        active = {
            row.username
            for row in conn.execute(text("SELECT username FROM app_user WHERE active = 1"))
        }
    for username, roles, region in DEMO_USERS:
        if username not in active:
            continue
        role = roles[0]
        tool_label = next(
            label for permission, label in group_by_permission.items()
            if permission in ROLE_PERMISSIONS[role]
        )
        groups[tool_label].append({
            "username": username,
            "role_label": role_label(role),
            "region": region,
        })
    return [(label, groups[label]) for label in groups]


def _demo_login_context(request: Request) -> dict:
    from app.seed import DEMO_PASSWORD

    return {
        "demo_accounts": _demo_accounts(request),
        "demo_password": DEMO_PASSWORD,
    }


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

    @app.exception_handler(OverflowError)
    async def _overflow(request: Request, exc: OverflowError):
        # An integer too large for a SQLite INTEGER is bad input, not a server fault.
        return await _app_error(request, AppError(422, "number is out of range"))

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
ANY = tuple(sorted(ALL_PERMISSIONS))
Page = Query(1, ge=1)
PageSize = Query(25, ge=1, le=MAX_PAGE_SIZE)


def _safe_next(target: str | None) -> str:
    return target if target and target.startswith("/") and not target.startswith("//") else "/"


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    return page(request, "login.html", None, next=_safe_next(next), error=None,
                **_demo_login_context(request))


@router.post("/login")
def login_submit(request: Request, username: str = Form(""), password: str = Form(""),
                 next: str = Form("/")):
    with tx(request) as conn:
        token = auth.login(conn, username, password)
    if token is None:
        return page(request, "login.html", None, status_code=401, next=_safe_next(next),
                    error="Wrong username or password", **_demo_login_context(request))
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


def _end_session(request: Request, response):
    with tx(request) as conn:
        auth.logout(conn, request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE)
    return response


@router.post("/logout")
def logout(request: Request, user: User = Depends(require(*ANY))):
    return _end_session(request, RedirectResponse("/login", status_code=303))


@router.post("/api/logout")
def api_logout(request: Request, user: User = Depends(require(*ANY))):
    return _end_session(request, JSONResponse({"logged_out": True}))


@router.get("/")
def landing(request: Request, user: User = Depends(require(*ANY))):
    for href, _label, perm, _section in NAV:
        if perm in user.permissions:
            return RedirectResponse(href, status_code=303)
    raise AppError(403, "permission denied")


# --- customers and charges (shared model) -----------------------------------------

@router.get("/api/customers")
def api_customers(request: Request, q: str | None = None, kyc_status: str | None = None,
                  sort: str | None = None, dir: str | None = None, page: int = Page,
                  page_size: int = Query(MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
                  user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        return customers.search_customers(conn, q, kyc_status or None, sort, dir, page, page_size, user=user)


@router.get("/api/customers/{customer_id}")
def api_customer(request: Request, customer_id: int, user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        return customers.get_customer(conn, customer_id, user)


@router.get("/api/charges")
def api_charges(request: Request, customer_id: int | None = None, q: str | None = None,
                refundable: bool = False, kyc_status: str | None = None, sort: str | None = None,
                dir: str | None = None, page: int = Page,
                page_size: int = Query(MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
                user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        return customers.search_charges(conn, q, customer_id, refundable, kyc_status or None,
                                        sort or "id", dir or "asc", page, page_size, user=user)


@router.get("/customers", response_class=HTMLResponse)
def customers_page(request: Request, q: str | None = None, kyc_status: str | None = None,
                   sort: str | None = None, dir: str | None = None, page_no: int = Query(1, ge=1, alias="page"),
                   page_size: int = PageSize, user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        result = customers.search_customers(conn, q, kyc_status or None, sort, dir, page_no, page_size,
                                            user=user)
    return lists.render(request, user, customers.CUSTOMER_LIST, result, "customers.html",
                        statuses=customers.KYC_STATUSES)


@router.get("/charges", response_class=HTMLResponse)
def charges_page(request: Request, q: str | None = None, show: str | None = None,
                 kyc_status: str | None = None, sort: str | None = None, dir: str | None = None,
                 page_no: int = Query(1, ge=1, alias="page"), page_size: int = PageSize,
                 user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        result = customers.search_charges(conn, q, None, show == "refundable", kyc_status or None,
                                          sort, dir, page_no, page_size, user=user)
        rules = settings.refund_rules(conn)
    return lists.render(request, user, customers.CHARGE_LIST, result, "charges.html", statuses=customers.KYC_STATUSES,
                picker=False, show=show or "all", rules=rules)


@router.get("/customers/{customer_id}", response_class=HTMLResponse)
def customer_page(request: Request, customer_id: int, q: str | None = None, sort: str | None = None,
                  dir: str | None = None, page_no: int = Query(1, ge=1, alias="page"),
                  page_size: int = PageSize, user: User = Depends(require("customer:read"))):
    with tx(request) as conn:
        customer = customers.get_customer(conn, customer_id, user)
        result = customers.search_charges(conn, q, customer_id, False, None, sort, dir, page_no, page_size,
                                          user=user)
        rules = settings.refund_rules(conn)
    return lists.render(request, user, customers.CHARGE_LIST, result, "customer_detail.html",
                        customer=customer, rules=rules)


# --- admin: settings ------------------------------------------------------------------

class LimitBody(BaseModel):
    value_cents: StrictInt
    reason: str | None = None


class SettingBody(BaseModel):
    value: StrictInt | StrictBool | list[str] | None = None
    reason: str | None = None


@router.get("/api/settings")
def api_settings(request: Request, user: User = Depends(require("settings:write"))):
    with tx(request) as conn:
        return {"items": [{"key": s["spec"].key, "label": s["spec"].label, "value": s["value"]}
                          for s in settings.all_settings(conn)]}


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


@router.put("/api/settings/{key}")
def api_set_setting(request: Request, key: str, body: SettingBody,
                    user: User = Depends(require("settings:write"))):
    with tx(request) as conn:
        return {"key": key, "value": settings.set_value(conn, user, key, body.value, body.reason)}


def _settings_page(request, user, status_code=200, error=None, saved=None):
    with tx(request) as conn:
        items = settings.all_settings(conn)
        for item in items:
            events = [e for e in audit.history(conn, "setting", item["spec"].key)]
            item["last"] = audit.describe(events[-1]) if events else None
    groups: dict[str, list] = {}
    for item in items:
        groups.setdefault(item["spec"].group, []).append(item)
    return page(request, "settings.html", user, status_code=status_code, groups=groups,
                max_cents=settings.AUTO_APPROVE_LIMIT_MAX_CENTS, error=error, saved=saved)


@router.get("/admin/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: User = Depends(require("settings:write"))):
    return _settings_page(request, user)


def _parse_setting(spec: settings.Spec, raw: str):
    raw = (raw or "").strip()
    if spec.kind == "cents":
        return to_cents(raw, spec.label.lower())
    if spec.kind == "bool":
        return raw == "on"
    if spec.kind == "list":
        return [line.strip() for line in raw.splitlines() if line.strip()]
    if spec.kind == "optional_int" and not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise AppError(422, f"{spec.label} must be a whole number")


@router.post("/admin/settings", response_class=HTMLResponse)
def settings_submit(request: Request, amount: str = Form(""), value_cents: str = Form(""),
                    reason: str = Form(""), user: User = Depends(require("settings:write"))):
    """The auto-approve limit, typed in dollars (`amount`); `value_cents` is still accepted."""
    try:
        if value_cents.strip():
            try:
                value = int(value_cents.strip())
            except ValueError:
                raise AppError(422, "limit must be a whole number of cents")
        else:
            value = to_cents(amount, "limit")
        with tx(request) as conn:
            settings.set_auto_approve_limit(conn, user, value, reason)
    except AppError as exc:
        if exc.status != 422:
            raise
        return _settings_page(request, user, status_code=422, error=exc.detail)
    return _settings_page(request, user, saved=settings.SPECS[settings.AUTO_APPROVE_LIMIT].label)


@router.post("/admin/settings/{key}", response_class=HTMLResponse)
def setting_submit(request: Request, key: str, value: str = Form(""),
                   reason: str = Form(""), user: User = Depends(require("settings:write"))):
    spec = settings.SPECS.get(key)
    if spec is None:
        raise AppError(404, f"setting {key} not found")
    try:
        with tx(request) as conn:
            settings.set_value(conn, user, key, _parse_setting(spec, value), reason)
    except AppError as exc:
        if exc.status != 422:
            raise
        return _settings_page(request, user, status_code=422, error=exc.detail)
    return _settings_page(request, user, saved=spec.label)


# --- admin: audit ---------------------------------------------------------------------

@router.get("/api/audit")
def api_audit(request: Request, entity: str | None = None, entity_id: str | None = None,
              q: str | None = None, actor: str | None = None, action: str | None = None,
              limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              user: User = Depends(require("audit:read"))):
    with tx(request) as conn:
        if entity and entity_id:
            return {"items": audit.history(conn, entity, entity_id)}
        if q or actor or action or entity:
            found = audit.search(conn, q, actor, action, entity, page_size=limit, offset=offset)
            return {"items": found["items"], "total": found["total"]}
        return {"items": audit.recent(conn, limit, offset)}


@router.get("/admin/audit", response_class=HTMLResponse)
def audit_page(request: Request, q: str | None = None, actor: str | None = None,
               action: str | None = None, entity: str | None = None, date_from: str | None = None,
               date_to: str | None = None, sort: str | None = None, dir: str | None = None,
               page_no: int = Query(1, ge=1, alias="page"), page_size: int = Query(50, ge=1, le=500),
               user: User = Depends(require("audit:read"))):
    with tx(request) as conn:
        result = audit.search(conn, q, actor or None, action or None, entity or None, date_from or None,
                              date_to or None, sort, dir, page_no, page_size)
        facets = audit.facets(conn)
    return lists.render(request, user, audit.AUDIT_LIST, result, "audit.html", facets=facets)
