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

## Block 3: review findings and the `tool1-done` independent check (01:03 to 01:08)

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

## Block 4: `tool2-done` tag and its independent check (01:08 to 01:17)

- 01:08 CI `test` was green for `aa7e5e3`; local `make verify` gave `46 passed, 1 skipped` and
  `AC3 PASS`. Tagged `tool2-done` on `aa7e5e3` and started the independent check (child session
  d683243801734933b55de141acb0079d, fresh clone of the tag, no build context).
- 01:13 the check reported 13 of 14 criteria PASS and **AC7 FAIL**: an SSN glued to a letter, digit or
  underscore (`ssn901-17-2231`, `_901-17-2231_`, `1901-17-2231`) was written unredacted to
  `audit_event.reason` and `refund.reason`, because the pattern required word boundaries. So the first
  `tool2-done` tag was on a commit that did not meet AC7; my own AC7 test had not covered that case.
- Fix (the only failed criterion): removed the word boundaries from the SSN pattern in
  `app/foundation/pii.py` and added `test_ac7_ssn_glued_to_other_characters_never_reaches_an_audit_row`,
  which fails without the fix and passes with it. No existing test was changed.
- Also reworded one README walkthrough step (the seed already has refunds on charges 1, 3 and 5).

The check's make output on `aa7e5e3` (result lines; full text in its session):

```
$ make setup        -> data/app.db: applied [1, 2]; now at [1, 2]                     [exit code: 0]
$ make seed         -> seeded demo data into data/app.db                               [exit code: 0]
$ make verify       -> 46 passed, 1 skipped, 1 warning in 9.25s
                       AC3 PASS: refund 1 and its 2 audit events survived the restart (new pid 10438)  [exit code: 0]
$ make test         -> 46 passed, 1 skipped, 1 warning in 6.64s                        [exit code: 0]
$ make verify       -> 46 passed, 1 skipped, 1 warning in 6.37s
                       AC3 PASS: refund 1 and its 2 audit events survived the restart (new pid 11947)  [exit code: 0]
$ make seed-scale   -> seeded 50000 refunds into data/scale.db: {'approved': 30000, 'pending_approval': 12500, 'rejected': 7500}  [exit code: 0]
$ make test-scale   -> 1 passed, 1 warning in 0.20s                                    [exit code: 0]
```

It also reported that no tool 1 assertion was weakened or removed between the tags.

Other things it found, logged and not fixed:
1. Separator variants (`901 17 2231`, `901.17.2231`, en dash, zero-width space, `4000-104729`) reach
   audit rows. These are not the exact stored values; listed in the README limitations.
2. Full values also show on the KYC review page `/kyc/{id}` (audited), not only on `/customers/{id}`.
   I treated the review page as a customer detail view; the spec names customer detail as the one
   exception, so this is a reading of the spec that a human should confirm.
3. The cross-tool rule and audit redaction are app-level only; direct SQL can bypass them.
4. With `PRAGMA foreign_keys = OFF`, direct SQL can insert a refund on a nonexistent charge and delete
   a charge that has refunds.
5. The refund form accepts scientific notation (`amount=1e2` creates a $100.00 refund).
6. An oversized `amount_cents` gets 422 with the "would exceed the charge amount" message.
7. A rejected-KYC customer's pending refund can still be rejected by an approver (the spec restricts
   only create and approve).
8. Not checked by it: whether tests leave `./data/` byte-identical, `make access-review`, a line by
   line read of the tests.

## Block 5: second `tool2-done` check (01:17 to 01:24)

- 01:17 CI `test` green on `61ce8e7`; local `make verify`: `47 passed, 1 skipped`, `AC3 PASS`.
  Force-moved `tool2-done` from `aa7e5e3` to `61ce8e7` and started a third fresh check (child session
  de15b69de0d5481c841a678596603ac7).
- 01:21 it reported **AC7 FAIL again**: a reason like `123-45-6901-17-2231` was masked once to
  `***-**-6901-17-2231`, which still holds the stored SSN `901-17-2231`. 14 `audit_event` rows and 18
  `refund` rows in its run held an exact stored SSN, readable by agents, approvers and the admin. So
  the moved tag was also on a commit that did not meet AC7. AC2, AC4, AC5, AC6, AC8, AC10, AC13 and
  AC14 passed in that run. No stored bank account value leaked.
- Fix (the failed criterion only): `redact_text` now repeats until nothing matches. Added
  `test_ac7_ssn_overlapping_an_ssn_shaped_prefix_never_reaches_an_audit_row` and
  `test_redacted_text_never_contains_an_ssn_or_long_digit_run` (20,000 generated strings); both fail
  without the fix. No existing test was changed.
- The tag is not moved again until a fresh check of the fixed commit reports AC7 as passing.

Its make output on `61ce8e7` (result lines; full text in its session), every command exit 0:

```
$ make setup        -> data/app.db: applied [1, 2]; now at [1, 2]
$ make seed         -> seeded demo data into data/app.db
$ make verify       -> 47 passed, 1 skipped, 1 warning in 6.40s
                       AC3 PASS: refund 1 and its 2 audit events survived the restart (new pid 10466)
$ make test         -> 47 passed, 1 skipped, 1 warning in 5.98s
$ make verify       -> 47 passed, 1 skipped, 1 warning in 6.11s
                       AC3 PASS: refund 1 and its 2 audit events survived the restart (new pid 11996)
$ make seed-scale   -> seeded 50000 refunds into data/scale.db: {'approved': 30000, 'pending_approval': 12500, 'rejected': 7500}
$ make test-scale   -> 1 passed, 1 warning in 0.18s
```

Other things it found, logged and not fixed:
1. One test is skipped in every `make test`, including CI (it is `tests/test_scale.py`, which needs
   the scale database and runs under `make test-scale`).
2. A limit change to the same value is still audited (before and after equal).
3. `/kyc/{id}` shows full values to `kyc1` (audited); same point as in block 4.
4. `data/app.db` held 3 refunds and 5 audit events after `make seed` (the seed creates them).

## Block 6: third `tool2-done` check and final tag (01:23 to 01:30)

- 01:23 pushed the fix as `45a1163`; CI `test` green. Started a fresh check of that commit (child
  session 6e541448799d41a1a25de40aef34cc0f) without moving the tag.
- 01:28 it reported no failed criterion: AC2, AC4, AC5, AC6, AC7, AC8, AC9, AC10, AC12, AC13 and AC14
  PASS (AC7 after about 12,500 HTTP writes: 0 exact stored SSN or bank account values in
  `audit_event` or `refund`). Force-moved `tool2-done` from `61ce8e7` to `45a1163`.

Its make output on `45a1163` (result lines; full text in its session):

```
$ make setup && make seed && make verify
data/app.db: applied [1, 2]; now at [1, 2]
seeded demo data into data/app.db
49 passed, 1 skipped, 1 warning in 6.94s
AC3: server stopped (pid 10495); refund 1 had 2 audit events
AC3 PASS: refund 1 and its 2 audit events survived the restart (new pid 10497)
[exit code: 0]
$ make test
49 passed, 1 skipped, 1 warning in 6.61s
[exit code: 0]
$ make verify
49 passed, 1 skipped, 1 warning in 6.39s
AC3: server stopped (pid 12005); refund 1 had 2 audit events
AC3 PASS: refund 1 and its 2 audit events survived the restart (new pid 12007)
[exit code: 0]
$ make seed-scale && make test-scale
seeded 50000 refunds into data/scale.db: {'approved': 30000, 'pending_approval': 12500, 'rejected': 7500}
1 passed, 1 warning in 0.17s
[exit code: 0]
```

Other things it found, logged and not fixed:
1. A reason starting with a NUL character returns 500, not 422 (the database CHECK on the reason
   fires; nothing is stored).
2. Malformed JSON returns 422 before the session and permission checks (same as block 3).
3. Reformatted SSN and account digits (spaces, dots, extra dashes) are stored unmasked (README
   limitation).

## End of build

**The `tool2-done` tag was moved twice.** It was first pushed on `aa7e5e3`, then `61ce8e7`; fresh
checks found AC7 failing on both. It now points at `45a1163`. `tool1-done` was never moved (`df09e33`).

**Elapsed (from the timestamps above):**
- Tool 1 (foundation, migration 001, refunds): 00:49 to 01:01, 12 minutes to the `tool1-done` tag.
- Tool 2: first passing local run 01:03 (2 minutes after starting); README, review fixes and the
  three check rounds ran until the final tag at 01:29, 28 minutes after `tool1-done`.
- Total: 00:49 to 01:30, 41 of the 120 minutes. Feature work stopped before minute 90.

**ACUs:** not visible to this session.

**`git diff --stat tool1-done tool2-done`:**

```
 README.md                          | 114 +++++++++++-
 app/foundation/pii.py              |  13 +-
 app/foundation/web.py              |   5 +
 app/kyc/__init__.py                |   0
 app/kyc/routes.py                  |  66 +++++++
 app/kyc/workflow.py                |  38 ++++
 app/main.py                        |   3 +-
 app/refunds/workflow.py            |  21 ++-
 app/templates/customer_detail.html |   1 +
 app/templates/customers.html       |   4 +-
 app/templates/kyc_queue.html       |  13 ++
 app/templates/kyc_review.html      |  24 +++
 app/templates/refund_form.html     |   1 +
 docs/BUILD_LOG.md                  | 168 ++++++++++++++++++
 migrations/002_kyc.sql             |  14 ++
 tests/conftest.py                  |  14 +-
 tests/test_cap_and_audit_sql.py    |  26 +++
 tests/test_kyc.py                  | 343 +++++++++++++++++++++++++++++++++++++
 tests/test_permissions.py          |  20 ++-
 19 files changed, 874 insertions(+), 14 deletions(-)
```

**Acceptance criteria.** "Check" is the fresh check of `45a1163`; "local" is my own run of
`make verify` / `make test-scale` on the same code.

| AC | Status | Observed by |
|---|---|---|
| AC1 | passing | check: `make setup && make seed && make verify` exit 0, `/login` 200 |
| AC2 | passing | check, local tests |
| AC3 | passing | check: `AC3 PASS` twice |
| AC4 | passing | check, local tests |
| AC5 | passing | check, local tests |
| AC6 | passing | check, local tests |
| AC7 | passing | check, after failing on `aa7e5e3` and `61ce8e7` |
| AC8 | passing | check, local tests |
| AC9 | passing | check, local tests |
| AC10 | passing | check, local tests |
| AC11 | passing | `make test-scale`: `1 passed` (check and local); small version in `make test`. The check of `45a1163` did not attack paging by hand; the check of `aa7e5e3` did and it passed |
| AC12 | passing | check, local tests |
| AC13 | passing for `45a1163` (run 43785970736, reported by the check). The run for the commit that adds this section finishes after this is written, so it is not recorded here |
| AC14 | passing | check, local test |

Nothing was cut: the 50,000-row seed and `make access-review` are both in. No permission check, cap,
threshold, audit rule or cross-tool rule was cut. Nothing here was verified by a human.

# BUILD_SPEC_2

Start: 02:16 UTC (2026-11-16). Hard stop per the spec is recorded below once the spec is read.
