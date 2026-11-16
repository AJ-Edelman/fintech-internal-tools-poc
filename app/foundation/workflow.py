"""A small workflow dispatcher shared by every tool.

A tool declares states, transitions, the permission each transition needs, and guards.
The engine checks them in a fixed order and writes one audit event per transition.
"""
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import text

from . import connectors, scope
from .audit import SYSTEM_ACTOR, write_audit
from .db import utcnow
from .errors import AppError


@dataclass(frozen=True)
class Transition:
    name: str
    source: str | None  # None means "create the record"
    target: str
    permission: str | None  # None means only the system actor may fire it
    guards: tuple[Callable, ...] = ()  # guard(conn, row, actor) raises AppError
    actor_column: str | None = None  # column stamped with the actor's name
    audit_extra: Callable | None = None  # audit_extra(row, actor) -> dict merged into "after"
    sends: tuple["connectors.Outbound", ...] = ()  # messages recorded with this transition


@dataclass(frozen=True)
class Workflow:
    entity: str
    table: str
    state_column: str
    states: tuple[str, ...]
    transitions: tuple[Transition, ...]
    audit_columns: tuple[str, ...] = ()  # non-sensitive columns snapshotted at creation
    updated_at_column: str | None = None
    customer_of: Callable | None = None  # customer_of(conn, row) -> customer id, for region scope
    by_name: dict = field(init=False, compare=False, hash=False)

    def __post_init__(self):
        names = {}
        for t in self.transitions:
            assert t.target in self.states and (t.source is None or t.source in self.states)
            names[t.name] = t
        object.__setattr__(self, "by_name", names)


class SystemActor:
    username = SYSTEM_ACTOR
    permissions = frozenset()
    is_system = True


SYSTEM = SystemActor()


def _authorize(t: Transition, actor) -> None:
    if t.permission is None:
        if not getattr(actor, "is_system", False):
            raise AppError(403, "only the system may perform this transition")
    elif t.permission not in actor.permissions:
        raise AppError(403, f"missing permission {t.permission}")


def _check_scope(conn, wf: Workflow, t: Transition, actor, row) -> None:
    """Out-of-region records are 404 for the permission this transition needs."""
    if wf.customer_of is None or t.permission is None or getattr(actor, "is_system", False):
        return
    customer_id = wf.customer_of(conn, row)
    if customer_id is not None:
        scope.check_customer(conn, actor, t.permission, customer_id)


def _send(conn, wf: Workflow, t: Transition, entity_id, row: dict, actor, audit_event_id: int) -> None:
    for out in t.sends:
        connectors.enqueue(conn, connector=out.connector, kind=out.kind, entity=wf.entity,
                           entity_id=entity_id, payload=out.payload(row, actor),
                           audit_event_id=audit_event_id)


def create(conn, wf: Workflow, name: str, actor, values: dict, reason: str | None) -> int:
    t = wf.by_name[name]
    assert t.source is None
    _authorize(t, actor)
    _check_scope(conn, wf, t, actor, values)
    for guard in t.guards:
        guard(conn, values, actor)
    row = dict(values)
    row[wf.state_column] = t.target
    if t.actor_column:
        row[t.actor_column] = actor.username
    if wf.updated_at_column:
        row[wf.updated_at_column] = utcnow()
    cols = ", ".join(row)
    params = ", ".join(f":{c}" for c in row)
    new_id = conn.execute(text(f"INSERT INTO {wf.table} ({cols}) VALUES ({params})"), row).lastrowid
    after = {c: row[c] for c in wf.audit_columns if c in row}
    after[wf.state_column] = t.target
    if t.audit_extra:
        after.update(t.audit_extra(row, actor))
    audit_id = write_audit(conn, actor=actor.username, action=f"{wf.entity}.{t.name}",
                           entity=wf.entity, entity_id=new_id, before=None, after=after, reason=reason)
    _send(conn, wf, t, new_id, {**row, "id": new_id}, actor, audit_id)
    return new_id


def fire(conn, wf: Workflow, name: str, entity_id: int, actor, reason: str | None) -> dict:
    t = wf.by_name[name]
    assert t.source is not None
    _authorize(t, actor)
    row = conn.execute(
        text(f"SELECT * FROM {wf.table} WHERE id = :id"), {"id": entity_id}
    ).mappings().first()
    if row is None:
        raise AppError(404, f"{wf.entity} {entity_id} not found")
    row = dict(row)
    _check_scope(conn, wf, t, actor, row)
    current = row[wf.state_column]
    if current != t.source:
        raise AppError(409, f"{wf.entity} {entity_id} is {current}, not {t.source}")
    for guard in t.guards:
        guard(conn, row, actor)
    sets = {wf.state_column: t.target}
    if t.actor_column:
        sets[t.actor_column] = actor.username
    if wf.updated_at_column:
        sets[wf.updated_at_column] = utcnow()
    assignments = ", ".join(f"{c} = :{c}" for c in sets)
    result = conn.execute(
        text(f"UPDATE {wf.table} SET {assignments} WHERE id = :_id AND {wf.state_column} = :_from"),
        {**sets, "_id": entity_id, "_from": t.source},
    )
    if result.rowcount != 1:
        raise AppError(409, f"{wf.entity} {entity_id} changed state concurrently")
    after = {wf.state_column: t.target}
    if t.actor_column:
        after[t.actor_column] = actor.username
    if t.audit_extra:
        after.update(t.audit_extra(row, actor))
    audit_id = write_audit(conn, actor=actor.username, action=f"{wf.entity}.{t.name}",
                           entity=wf.entity, entity_id=entity_id, before={wf.state_column: current},
                           after=after, reason=reason)
    row.update({k: v for k, v in sets.items()})
    _send(conn, wf, t, entity_id, row, actor, audit_id)
    return row
