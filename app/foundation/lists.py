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


def run(conn, spec: ListSpec, user, params: Mapping[str, str]) -> dict:
    """items, total (exact), page, pages, page_size, q, sort, dir, filters."""
    raise NotImplementedError  # stage 0 stub: worker B implements


def render(request, user, spec: ListSpec, result: dict, template: str = "list.html", **ctx):
    raise NotImplementedError  # stage 0 stub: worker B implements
