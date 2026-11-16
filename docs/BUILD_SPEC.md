# BUILD_SPEC: Shared internal-tools foundation + two tools

You are building a working prototype in this repo. Read this file only; don't read the rest of `docs/`. Work on a new branch, open a PR, and push the two tags named below. **Synthetic data only. No secrets committed.**

## Goal
Show the pattern for a fintech building many internal tools on one shared foundation:
- **Tool 1:** refund requests with maker-checker approval (requests only; no money moves).
- **Tool 2:** a light KYC review (a review workflow; no identity verification).
- **Shared:** one `customer` model, one permission model, one audit log, one workflow engine.

## Stack (fixed)
Python 3.11, FastAPI, SQLAlchemy, SQLite, Jinja2 pages (tables and forms only), pytest, GitHub Actions.

| Command | Must do |
|---|---|
| `make setup` | Install dependencies and apply migrations |
| `make seed` | Load the demo data into `./data/` |
| `make run` | Start the server in the foreground |
| `make test` | Run the tests on temporary databases; needs no server and never touches `./data/` |
| `make verify` | `make test` plus AC3; starts and stops any server it needs |
| `make seed-scale` | Build a separate scale database; never touches the demo database |
| `make access-review` | Print who holds which role |

## Foundation (`app/foundation/`), used by both tools
1. **Identity (stubbed):** demo users log in with a password and get a session cookie. Everything except login requires a session. Role assignments are rows in `role_assignment`, read on the server for every request.
2. **Permissions:** every route checks a permission, never a role name. The mapping lives in one place:

   | Role | Permissions |
   |---|---|
   | `refund_agent` | `customer:read`, `refund:read`, `refund:create` |
   | `refund_approver` | `customer:read`, `refund:read`, `refund:approve` |
   | `kyc_reviewer` | `customer:read`, `pii:read`, `kyc:review` |
   | `admin` | `access_review:read`, `audit:read` (not a superuser) |

3. **Status codes:** no session → 401 (API) or redirect to login (page); permission denied → 403; rule or input violation → 422; decision on a record that is no longer pending → 409.
4. **Audit:** `audit_event` holds actor, action, entity, entity id, before, after, reason and UTC time. The database rejects UPDATE and DELETE on it. Each change and its audit event commit together or not at all. **Audit rows never contain SSN or bank account values.**
5. **Workflow engine:** each tool declares states, transitions, the permission each transition needs, and guards. Every transition writes an audit event. Keep it a small dispatcher: no DSL, plugins or background jobs.
6. **PII:** `customer.ssn` shows as `***-**-1234` and `bank_account` as `****1234` everywhere, including lists and pages. The one exception is the customer detail view for a caller with `pii:read`, and each such view writes an audit event naming the fields shown.
7. **Migrations:** numbered SQL files applied in order and recorded in the database. Schema changes never recreate the database.

## Shared model
- `customer`: id, name, email, ssn, bank_account
- `charge`: id, customer_id, amount_cents (integer, positive), created_at

## Tool 1: Refunds (migration 001; tag `tool1-done` on a commit where `make test` passes)
- A `refund_agent` requests a refund on a charge, with a positive amount in cents and a reason.
- **Cap:** pending plus approved refunds on a charge may never exceed the charge amount. The database enforces this, so a direct SQL insert is rejected too.
- **Threshold:** a request is approved automatically only if it keeps the charge's pending plus approved total at or below `AUTO_APPROVE_LIMIT_CENTS` (one setting, default 50000, read in one place). The audit event records `system` as the approver and the agent as the requester. Otherwise it is `pending_approval`.
- A `refund_approver` approves or rejects a pending request, with a reason. Nobody can decide a request they created.
- Pages: refund list (paged on the server, filter by status), request form, approval queue, and a refund detail page showing its audit history.
- API: `GET /api/refunds?status=&page=&page_size=` returns items ordered by id, plus the total.

## Tool 2: KYC review (migration 002; tag `tool2-done`)
- Migration 002 adds `customer.kyc_status` (`pending` | `approved` | `rejected`). Existing customers become `pending`; data and audit history are kept.
- A `kyc_reviewer` works a queue of pending customers, opens one, and approves or rejects it with a reason, through the workflow engine.
- **Cross-tool rule:** a refund can be created or approved only if the customer's `kyc_status` is `approved`.
- Tool 1 tests must still pass. You may update their setup data; you may not weaken what they assert.

## Seed data
- `make seed`: about 20 customers (in mixed KYC states once tool 2 adds the column), about 40 charges (some over $1,000 on approved customers), and users `agent1`, `agent2` (refund_agent), `approver1` (refund_approver), `kyc1` (kyc_reviewer), `admin1` (admin), all with password `demo`.
- `make seed-scale`: 50,000 refunds with a fixed, known count per status.

## Acceptance criteria
Each is an automated test through HTTP unless marked. **[T1]** must pass at `tool1-done`; the rest at `tool2-done`.

| # | Criterion |
|---|---|
| AC1 | [T1] From a fresh clone, `make setup && make seed && make verify` passes, and `make run` serves the login page |
| AC2 | [T1] An agent requests $750 → `pending_approval` → an approver approves → `approved`, with an audit event per step. $500.00 on a fresh charge is approved by `system`; $500.01 is pending. With the limit set to another value, the boundary moves with it |
| AC3 | [T1] (process) A refund and its audit events survive stopping and restarting the server |
| AC4 | [T1] A test user holding both refund roles cannot approve their own request: 403, state unchanged, no approval audit event |
| AC5 | [T1] An agent calling the approve endpoint gets 403. At `tool2-done`, a refund agent calling the KYC decision endpoint also gets 403 |
| AC6 | [T1] Over the cap → 422 through the API and the form, including when two requests together exceed the charge. Rejecting a request frees its amount. (SQL) A direct insert over the cap fails |
| AC7 | An agent sees masked values. A KYC reviewer sees full values on customer detail only, and that view is audited. No audit row contains a raw SSN or bank account |
| AC8 | [T1] (SQL) UPDATE and DELETE on `audit_event` each fail and leave the row unchanged |
| AC9 | [T1] A refund's history (who, what, before, after, reason, when) can be rebuilt from `audit_event` alone |
| AC10 | Creating a refund for a `pending` or `rejected` customer → 422. Approving a refund that was requested before migration 002, for a customer who is not approved → 422 |
| AC11 | On the scale database, `GET /api/refunds` with a status filter returns the known total (over 10,000) and the right rows on the first, a middle and the last page. A small version of this test runs in `make test` |
| AC12 | [T1] Admin lists role assignments; other users get 403; no session gets 401 |
| AC13 | (CI) GitHub Actions runs `make test` on every push, and the run for the final commit is green |
| AC14 | (migration) A database at 001 with customers, refunds and audit events upgrades to 002 with every row intact |

## README (required)
What it does, prerequisites, clean-start steps, demo users, a short demo walkthrough, which test covers each AC, how to add tool N (the steps tool 2 followed), and limitations. Limitations must include: no real SSO or MFA; no CSRF tokens; the auto-approve limit changes only through a code change, not a screen; no production hosting, encryption at rest or backups; no retention or disposal; the audit log is append-only for the app but not tamper-proof against whoever controls the database file; no KYC claim/lock, escalation or documents; no data migrated from an existing platform; the scale test shows correct paging, not performance.

## Build log (`docs/BUILD_LOG.md`, append as you go)
- Per work block: start and end time, what was asked, what you did, failures and rework.
- Every tool 1 file changed during tool 2, labelled: expected rule change, setup-data change, foundation change, or assertion change (with the reason).
- At the end: elapsed time for each tool, `git diff --stat tool1-done tool2-done`, ACUs if visible, and each AC as passing, failing or not run.
- Record only what you observed. Don't estimate missing numbers, and don't mark anything as verified by a human.

## Time limit: 120 minutes, hard
Stop feature work at minute 90 and use the rest to verify, push and write up. At 120, stop and report the real status. If tool 1 isn't passing by minute 70, skip tool 2 and say so. Cut first: the 50,000-row seed (keep the small paging test), then `make access-review`. Never cut a permission check, the cap, the threshold, audit rules or the cross-tool rule without logging it.
