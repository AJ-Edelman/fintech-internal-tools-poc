"""Shared list screens (BUILD_SPEC_2 item 2). Owner after stage 0: worker B.

A tool declares a ListSpec; `run` does search, sort, filter, region scope and paging on the
server with an exact total; `render` shows it with the one shared template.
"""
from dataclasses import dataclass, field
from typing import Callable, Mapping


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    expr: str  # SQL expression
    searchable: bool = False
    sortable: bool = False
    kind: str = "text"  # text | money | date | status | masked | link | age


@dataclass(frozen=True)
class Filter:
    key: str  # query parameter name
    label: str
    expr: str  # SQL expression compared for equality
    options: tuple[tuple[str, str], ...]  # (value, label)


@dataclass(frozen=True)
class ListSpec:
    name: str
    permission: str  # the permission in use, for region scope
    source: str  # FROM clause, joins included
    columns: tuple[Column, ...]
    filters: tuple[Filter, ...] = ()
    customer_id_expr: str | None = None  # None: not customer data, no region scope
    where: tuple[str, ...] = ()  # fixed conditions, e.g. a queue's status
    default_sort: str = "id"
    default_dir: str = "asc"
    tiebreak: str = "id"
    waiting_since: str | None = None  # queues: SQL timestamp; adds a waiting column, oldest first
    row_view: Callable[[dict], dict] | None = None  # e.g. PII masking
    extra: dict = field(default_factory=dict)


REGISTRY: dict[str, ListSpec] = {}


def register(spec: ListSpec) -> ListSpec:
    REGISTRY[spec.name] = spec
    return spec


def _search_exprs(spec: ListSpec) -> tuple[str, ...]:
    # masked columns only ever match on their last four characters, never the full value
    return tuple(f"substr({c.expr}, -4)" if c.kind == "masked" else c.expr
                 for c in spec.columns if c.searchable)


def run(conn, spec: ListSpec, user, params: Mapping[str, str]) -> dict:
    """items, total (exact), page, pages, page_size, q, sort, dir, filters."""
    from . import scope
    from .errors import AppError
    from .listing import MAX_PAGE_SIZE, run_list

    register(spec)
    where, binds = list(spec.where), dict(spec.extra.get("params", {}))
    filters = {}
    for i, f in enumerate(spec.filters):
        value = params.get(f.key) or ""
        if value:
            if value not in {v for v, _ in f.options}:
                raise AppError(422, f"{f.key} must be one of " + ", ".join(v for v, _ in f.options))
            where.append(f"{f.expr} = :_f{i}")
            binds[f"_f{i}"] = value
        filters[f.key] = value
    if spec.customer_id_expr:
        cond, cparams = scope.customer_filter(user, spec.permission, spec.customer_id_expr)
        where.append(f"({cond})")
        binds.update(cparams)
    sorts = {c.key: c.expr for c in spec.columns if c.sortable}
    select = ", ".join(f"{c.expr} AS {c.key}" for c in spec.columns)
    default_sort, default_dir = spec.default_sort, spec.default_dir
    if spec.waiting_since:
        sorts["waiting"] = spec.waiting_since
        select += f", {spec.waiting_since} AS waiting_since"
        if spec.default_sort == "id" and spec.default_dir == "asc":
            default_sort, default_dir = "waiting", "asc"
    if "select" in spec.extra:
        select = spec.extra["select"] + (f", {spec.waiting_since} AS waiting_since" if spec.waiting_since else "")
    try:
        page = max(1, int(params.get("page") or 1))
        page_size = min(MAX_PAGE_SIZE, max(1, int(params.get("page_size") or 25)))
    except ValueError:
        raise AppError(422, "page and page_size must be integers")
    result = run_list(conn, select=select, frm=spec.source, where=where, params=binds,
                      search=_search_exprs(spec), q=params.get("q"), sorts=sorts,
                      default_sort=default_sort, default_dir=default_dir, tiebreak=spec.tiebreak,
                      sort=params.get("sort") or None, direction=params.get("dir") or None,
                      page=page, page_size=page_size,
                      offset=int(params["offset"]) if params.get("offset") not in (None, "") else None)
    if spec.waiting_since:
        for row in result["items"]:
            row["waiting"] = _waiting(row.get("waiting_since"))
    if spec.row_view:
        result["items"] = [spec.row_view(row) for row in result["items"]]
    result["filters"] = filters
    result.update(filters)
    result["list_name"] = spec.name
    return result


def _waiting(since) -> str:
    from datetime import datetime, timezone
    if not since:
        return ""
    try:
        start = datetime.fromisoformat(str(since).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    secs = max(0, int((datetime.now(timezone.utc) - start).total_seconds()))
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h {secs % 3600 // 60}m"
    return f"{secs // 86400}d {secs % 86400 // 3600}h"


def render(request, user, spec: ListSpec, result: dict, template: str = "list.html", **ctx):
    from .web import page
    register(spec)
    return page(request, template, user, result=result, spec=spec, shared_list=spec.name, **ctx)
