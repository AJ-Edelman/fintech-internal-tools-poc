"""Admin users and access routes. Owner after stage 0: worker C."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from . import lists, users
from .auth import User, require
from .errors import AppError
from .listing import MAX_PAGE_SIZE
from .permissions import ROLE_LABELS, ROLE_PERMISSIONS
from .web import page, tx

router = APIRouter()
Page = Query(1, ge=1)
PageSize = Query(25, ge=1, le=MAX_PAGE_SIZE)


class NewUserBody(BaseModel):
    username: str
    password: str
    role_names: list[str] = []
    region: str = "ALL"


class RolesBody(BaseModel):
    role_names: list[str]
    region: str | None = None


class ActiveBody(BaseModel):
    active: bool


@router.get("/api/access-review")
def api_access_review(request: Request, user: User = Depends(require("access_review:read"))):
    with tx(request) as conn:
        return {"assignments": users.role_assignments(conn)}


@router.get("/api/users")
def api_users(request: Request, q: str | None = None, role: str | None = None, status: str | None = None,
              sort: str | None = None, dir: str | None = None, page: int = Page,
              page_size: int = Query(MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
              user: User = Depends(require("access_review:read"))):
    with tx(request) as conn:
        return users.list_users(conn, q, role or None, status or None, sort, dir, page, page_size)


@router.post("/api/users", status_code=201)
def api_add_user(request: Request, body: NewUserBody, user: User = Depends(require("user:manage"))):
    with tx(request) as conn:
        return users.add_user(conn, user, body.username, body.password, body.role_names, body.region)


@router.put("/api/users/{user_id}/roles")
def api_set_roles(request: Request, user_id: int, body: RolesBody,
                  user: User = Depends(require("user:manage"))):
    with tx(request) as conn:
        return users.set_roles(conn, user, user_id, body.role_names, body.region)


@router.put("/api/users/{user_id}/active")
def api_set_active(request: Request, user_id: int, body: ActiveBody,
                   user: User = Depends(require("user:manage"))):
    with tx(request) as conn:
        return users.set_active(conn, user, user_id, body.active)


def _access_page(request, user, status_code=200, error=None, saved=None, **filters):
    with tx(request) as conn:
        result = users.list_users(conn, **filters) if filters else users.list_users(conn)
        overview = users.role_overview(conn)
    return lists.render(request, user, users.ACCESS_REVIEW_LIST, result, "access_review.html",
                status_code=status_code, overview=overview, role_labels=ROLE_LABELS, all_roles=list(ROLE_PERMISSIONS),
                error=error, saved=saved, min_password=users.MIN_PASSWORD,
                region_choices=users.REGION_CHOICES)


@router.get("/admin/access-review", response_class=HTMLResponse)
def access_review_page(request: Request, q: str | None = None, role: str | None = None,
                       status: str | None = None, sort: str | None = None, dir: str | None = None,
                       page_no: int = Query(1, ge=1, alias="page"), page_size: int = PageSize,
                       saved: str | None = None, user: User = Depends(require("access_review:read"))):
    return _access_page(request, user, saved=saved, q=q, role=role or None, status=status or None,
                        sort=sort, direction=dir, page=page_no, page_size=page_size)


def _user_action(request, user, action):
    try:
        with tx(request) as conn:
            changed = action(conn)
    except AppError as exc:
        if exc.status != 422:
            raise
        return _access_page(request, user, status_code=422, error=exc.detail)
    return RedirectResponse("/admin/access-review?saved=" + quote(changed["username"]), status_code=303)


@router.post("/admin/users", response_class=HTMLResponse)
def add_user_submit(request: Request, username: str = Form(""), password: str = Form(""),
                    role_names: list[str] = Form([]), region: str = Form("ALL"),
                    user: User = Depends(require("user:manage"))):
    return _user_action(request, user,
                        lambda conn: users.add_user(conn, user, username, password, role_names, region))


@router.post("/admin/users/{user_id}/roles", response_class=HTMLResponse)
def set_roles_submit(request: Request, user_id: int, role_names: list[str] = Form([]),
                     region: str = Form(""), user: User = Depends(require("user:manage"))):
    return _user_action(request, user,
                        lambda conn: users.set_roles(conn, user, user_id, role_names, region or None))


@router.post("/admin/users/{user_id}/active", response_class=HTMLResponse)
def set_active_submit(request: Request, user_id: int, active: str = Form(""),
                      user: User = Depends(require("user:manage"))):
    return _user_action(request, user,
                        lambda conn: users.set_active(conn, user, user_id, active == "1"))


