# Build log

Times are UTC on 2026-11-16, read from `date -u` on the build machine. Only observed facts are recorded here.
Nothing in this log was verified by a human.

## Block 1: foundation, migration 001, tool 1 (00:49 to 01:02)

**Asked:** implement `docs/BUILD_SPEC.md` on a new branch and open a PR; build `app/foundation/` and
migration 001 first, then tool 1; tag `tool1-done` only when its criteria pass; delegate self-contained
pieces to background subagents once the foundation is stable; at each tag have a fresh subagent with no
build context run `make test` and `make verify` and try to break the criteria.

**Did:**
- 00:49 clock started. Read `docs/BUILD_SPEC.md` (also opened `docs/TRACKER.md` once before reading the
  spec's "read this file only" line; nothing from it was used).
- Built `app/foundation/` (db + migrations, auth, permissions, audit, workflow engine, pii, settings,
  customers, web), `migrations/001_foundation_and_refunds.sql`, `app/refunds/`, templates, seeds,
  `Makefile`, CI workflow, and tests for the [T1] criteria.

**Delegation:** none. This session has no in-process background-subagent tool, so the pieces offered for
delegation (scale seed and paging test, CI and Makefile, README) were written by the main session. The
independent checks run as separate child Devin sessions on a fresh clone of the pushed tag.

**Failures and rework:**
- First test run: `INSERT OR REPLACE` on `audit_event` replaced a row without firing the DELETE trigger
  (AC8 test failed). Fixed in migration 001 with a `BEFORE INSERT` trigger that rejects an existing id.
- My test had hand-computed counts for the 230-row paging data wrong (138/57/35); the seed's own formula
  gives 142/55/33. Corrected the expected numbers in the test, not the seed.
- Newer FastAPI wraps included routers, so the "every route checks a permission" test could not walk
  `app.routes` directly; added a helper that walks into included routers and fails on anything else.
- The role-name test matched the URL prefix `/admin/`; narrowed it to quoted role names and `.roles`.

**Observed at 01:00 (before commit):** `make setup && make seed && make verify` passed
(`34 passed, 1 skipped`, then `AC3 PASS`); the skip is the 50,000-row test, which only runs under
`make test-scale`. `make run` served `/login` with 200. `make seed-scale` built 50,000 refunds
(30,000 approved / 12,500 pending_approval / 7,500 rejected) and `make test-scale` passed (`1 passed`).
