"""One server-side search, filter, sort and page helper shared by every list."""
from sqlalchemy import text

from .errors import AppError

MAX_PAGE_SIZE = 200


def run_list(conn, *, select: str, frm: str, sorts: dict[str, str], default_sort: str, tiebreak: str,
             where: list[str] | None = None, params: dict | None = None, search: tuple[str, ...] = (),
             q: str | None = None, sort: str | None = None, direction: str | None = None,
             page: int = 1, page_size: int = 25, default_dir: str = "asc",
             offset: int | None = None) -> dict:
    sort = sort or default_sort
    direction = (direction or default_dir).lower()
    if sort not in sorts:
        raise AppError(422, "sort must be one of " + ", ".join(sorts))
    if direction not in ("asc", "desc"):
        raise AppError(422, "dir must be asc or desc")
    where, params = list(where or []), dict(params or {})
    q = (q or "").strip()
    if q and search:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["_q"] = f"%{escaped}%"
        where.append("(" + " OR ".join(f"CAST({expr} AS TEXT) LIKE :_q ESCAPE '\\'" for expr in search) + ")")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(text(f"SELECT COUNT(*) FROM {frm} {clause}"), params).scalar()
    order = f"{sorts[sort]} {direction}, {tiebreak} {direction}"
    rows = conn.execute(
        text(f"SELECT {select} FROM {frm} {clause} ORDER BY {order} LIMIT :_l OFFSET :_o"),
        {**params, "_l": page_size, "_o": (page - 1) * page_size if offset is None else offset},
    ).mappings()
    return {"items": [dict(r) for r in rows], "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size)), "q": q, "sort": sort, "dir": direction}
