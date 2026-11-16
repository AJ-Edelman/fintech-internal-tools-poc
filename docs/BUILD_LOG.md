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

**01:00 to 01:01:** committed `df09e33`, pushed the branch, opened PR #3, pushed tag `tool1-done` on
`df09e33`, and started the independent check as a child session on a fresh clone of the tag.

## Block 2: tool 2 (01:01 to 01:03)

**Asked:** tool 2 per the spec, not before the `tool1-done` tag.

**Did:** `migrations/002_kyc.sql` (adds `customer.kyc_status` in place), `app/kyc/` (workflow declared on
the shared engine, routes, two templates), the cross-tool guard on refund `request` and `approve`, and
`tests/test_kyc.py` (AC7, AC10, AC14) plus the AC5 KYC test.

**Order note:** tool 2 was started after `tool1-done` was pushed but before the independent check of
that tag had reported (the report arrived at 01:06). The check found no failed [T1] criterion.

**Failures and rework:** the first run after adding the guard failed 19 tool 1 tests, because their
customers had no KYC status. Fixed by setup data only (see the table). No other rework.

**Tool 1 files changed during tool 2:**

| File | Label | Reason |
|---|---|---|
| `app/refunds/workflow.py` | expected rule change | added `guard_customer_kyc_approved` to `request` and `approve` |
| `app/refunds/workflow.py` | foundation change (review fix) | refund reason is redacted before it is stored |
| `app/main.py` | foundation change | registers the KYC router |
| `app/foundation/web.py` | foundation change (review fix) | `OverflowError` is rendered as 422 |
| `app/templates/customers.html`, `customer_detail.html`, `refund_form.html` | expected rule change | show KYC status; form says refunds need an approved customer |
| `tests/conftest.py` | setup-data change | customer 1 is KYC-approved, added rejected customer 3 and charge 8; customer 2 stays pending |
| `tests/test_permissions.py` | assertion change (added) | new AC5 KYC test; role-name test now also scans `app.kyc.routes`. Nothing removed or loosened |
| `tests/test_cap_and_audit_sql.py` | assertion change (added) | two new tests for the review fixes. Nothing removed or loosened |
| `README.md` | not a tool 1 file | written in this block |

No existing tool 1 assertion was changed.

## Block 3: review findings and the `tool1-done` independent check (01:03 to 01:10)

**Devin Review on `df09e33`** (automatic, auto-fix on) raised 4 findings. Each fix is its own commit:
- Refund reasons shown unmasked to refund roles: fixed in `4716430` (redact before storing).
- `INSERT OR REPLACE` on `charge` bypasses the cap: fixed in `3c6d06b` (trigger added in migration 002,
  so databases already at 001 get it).
- Integers beyond 64 bits gave 500: fixed in `7495db9` (422).
- Redaction misses identifiers typed with other separators (`900 12 3456`): not fixed, left for a
  human, listed in the README limitations.

**Independent check of `tool1-done`** (child session 902077e48a8b4d9e83ae714d9fe1bda7, fresh clone of
`df09e33`, no build context). It reported AC1, AC2, AC3, AC4, AC5, AC6, AC8, AC9 and AC12 as PASS and
no failed [T1] criterion, so nothing was fixed on its account. Its make output:

```
$ make setup && make seed && make verify
data/app.db: applied [1]; now at [1]
seeded demo data into data/app.db
34 passed, 1 skipped, 1 warning in 4.22s
AC3: server stopped (pid 10145); refund 1 had 2 audit events
AC3 PASS: refund 1 and its 2 audit events survived the restart (new pid 10147)
exit code: 0
$ make test
34 passed, 1 skipped, 1 warning in 3.88s
exit code: 0
$ make verify
34 passed, 1 skipped, 1 warning in 3.98s
AC3: server stopped (pid 11012); refund 1 had 2 audit events
AC3 PASS: refund 1 and its 2 audit events survived the restart (new pid 11014)
exit code: 0
```
(Lines trimmed to the result lines; the checker's full output is in its session.)

Other things it found, logged and not fixed unless noted:
1. Cap bypass by `INSERT OR REPLACE` on `charge`: same as the review finding, fixed in `3c6d06b`. With
   `PRAGMA foreign_keys` off (the raw SQLite default; the app turns it on), renumbering or deleting a
   charge and inserting a refund on a nonexistent charge also succeed. Not fixed.
2. Malformed JSON on `POST /api/refunds` and the approve endpoint returns 422 before the session and
   permission checks (no session gets 422, not 401; wrong role gets 422, not 403). Nothing is changed
   by such a request. Not fixed.
3. Integers beyond 64 bits gave 500: same as the review finding, fixed in `7495db9`.
4. The auto-approve limit is only checked in the app: `UPDATE setting SET value='9999999'` by SQL is
   accepted and then used; a non-numeric value makes refund requests return 500. Not fixed.
5. Refund reason stored unredacted: same as the review finding, fixed in `4716430`. Spaced SSN form is
   still missed.
6. Other rules are app-only under direct SQL: self-decision, moving a rejected refund back to pending,
   a forged `audit_event` INSERT, dropping triggers; the username check blocks `system` but allows
   `System`. Not fixed.
7. No logout route and no session expiry. Not fixed. README was two lines at that tag (written since).
8. Test gaps: AC4's form check covers approve only (the checker tested reject by hand: 403); no test
   sent malformed JSON. Not changed.
