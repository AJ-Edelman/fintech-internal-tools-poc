# BUILD_SPEC: Shared internal-tools foundation + two tools (scope A2)

You are building a working prototype in this repo. Read this file only; don't read the rest of `docs/`, to keep the build independent of the planning context. **Synthetic data only. No production credentials.**

## Goal
Show the pattern for a fintech building many internal tools on one shared foundation, rather than standalone apps:
- **Tool 1:** refund requests with maker-checker approval.
- **Tool 2:** a light KYC review.
- **Shared:** both tools use one `customer` model, one permission model, one audit log and one workflow engine.

## Stack (fixed)
- Python 3.11+, FastAPI, SQLAlchemy, and SQLite (a file under `./data/`, which must persist across restarts).
- Server-rendered HTML (Jinja2). Keep the UI minimal: tables plus forms.
- pytest. GitHub Actions runs the tests on every push.
- One command for each step: `make setup`, `make seed`, `make run`, `make test`, `make verify`.

## Foundation (`app/foundation/`), used by every tool
1. **Identity (stubbed):** demo users log in with a demo password, which gives them a session. Every API and page requires a session. Role assignments are rows in a `role_assignment` table.
2. **Permissions:** a `require(permission)` check on every route. Roles map to permissions in one place. Permissions are enforced on the server and never only hidden in the UI.
3. **Audit:** an append-only `audit_event` table with actor, action, entity, entity id, before (JSON), after (JSON), reason and timestamp. **SQLite triggers must reject UPDATE and DELETE** on this table. No role, including admin, can edit it.
4. **Workflow engine:** a small, generic state machine. Each tool declares its states, its transitions, the permission each transition needs, and guards. It has a built-in `no_self_approval` guard. Every transition writes an audit event.
5. **Data-layer rules:** validation lives in the shared service or model layer, so every tool and every endpoint that writes a table enforces it. Use DB CHECK constraints where they fit.
6. **PII masking:** serialization depends on the caller's role. `customer.ssn` shows as `***-**-1234` and `customer.bank_account` shows as `****1234` unless the caller has `pii:read`. Each unmasked read writes an audit event.
7. **Access review:** `GET /admin/role-assignments` (admin only) and `make access-review` list who holds which role.

## Shared model
- `customer`: id, name, email, ssn, bank_account
- `charge`: id, customer_id, amount_cents, created_at

## Tool 1: Refunds (build first; tag `tool1-done` when it's finished)
- A `refund_agent` creates a refund request for a charge, with an amount and a reason.
- **Rule:** the total of all non-rejected refunds on a charge may not exceed the charge amount.
- A request of $500 or less moves to `approved` automatically. A request over $500 stays `pending_approval` until a `refund_approver` approves or rejects it, with a reason. The requester can never approve their own request.
- States: `pending_approval`, `approved`, `rejected`.
- Pages: the list of refunds (paged on the server) and a form to create a request. Approvers see an approval queue.

## Tool 2: KYC review (build second, on top of `tool1-done`; tag `tool2-done` when it's finished)
- **Shared-model change (deliberate):** add `customer.kyc_status` (`pending` | `approved` | `rejected`) with a migration.
- A `kyc_reviewer` works a queue of `pending` customers, opens a customer (unmasked PII, which is audited) and approves or rejects with a required reason. The decision uses the workflow engine.
- **Cross-tool rule, enforced on the server in the refunds service:** a refund cannot be created or approved unless the customer's `kyc_status` is `approved`.
- After tool 2, every tool 1 test must still pass. Some may need updating (for example, seeded customers need an approved KYC status). **Record every tool 1 test or file you had to change, and why**, in `docs/BUILD_LOG.md`. That record is the measure of coupling.

## Seed data
- `make seed`: about 20 customers in mixed KYC states and about 40 charges, plus these demo users, all with password `demo`: `agent1` (refund_agent), `agent2` (refund_agent), `approver1` (refund_approver), `kyc1` (kyc_reviewer), `admin1` (admin).
- `make seed-scale`: 50,000 customers and charges, used only for the paging check.

## Acceptance criteria (each one is an automated test against the HTTP API, not the UI)
| # | Criterion |
|---|---|
| AC1 | From a fresh clone, `make setup && make seed && make run` starts the app, and `make verify` passes |
| AC2 | The refund flow works end to end: an agent creates a $750 refund → it is `pending_approval` → the approver approves it → it is `approved`, and audit events exist for each step |
| AC3 | **Persistence:** create a refund, restart the server process, and the refund and its audit events are still there |
| AC4 | **Denied (self-approval):** a user who holds both roles cannot approve their own request. The response is 403 and the state is unchanged |
| AC5 | **Denied (role):** an agent calling the approve endpoint directly gets 403 |
| AC6 | **Rule:** a refund over the remaining refundable amount is rejected with 422, both through the API and through the form |
| AC7 | **Masking:** an agent who fetches a customer gets masked SSN and bank account. A KYC reviewer gets full values, and an audit event records that read |
| AC8 | **Tamper resistance:** a direct SQL UPDATE or DELETE on `audit_event` fails |
| AC9 | **Reconstruction:** a refund's full history (who, what, before and after, reason, when) can be rebuilt from `audit_event` alone |
| AC10 | **Cross-tool rule:** a refund for a customer whose KYC is `pending` or `rejected` gets 422 |
| AC11 | **Scale:** after `make seed-scale`, a filtered, paged list returns the correct total (more than 10,000) and the correct pages |
| AC12 | **Access review:** admin can list role assignments; anyone else gets 403 |
| AC13 | CI runs `make test` on push and passes |

## Non-goals
These are out of scope; name them in the README's Limitations section:
- Real SSO or MFA.
- Production hosting, encryption at rest, backups.
- Retention and disposal.
- KYC claim/lock, escalation, document uploads.
- The feature-flag tool.
- Migrating data from the platform.
- UI polish.

## README (required)
Cover: what it does, prerequisites, clean-start steps, seed data and demo users, how to run `make verify`, how the acceptance criteria map to tests, how to add tool N (the steps tool 2 followed), limitations, and reviewer access (local only).

## Build log (`docs/BUILD_LOG.md`, append as you go)
For each work block, record:
- start and end time;
- what you were asked to do and what you did;
- failures and rework;
- files and tests changed in tool 1 during tool 2.

At the end, record:
- tool 1 and tool 2 elapsed time;
- `git diff --stat tool1-done tool2-done`;
- ACUs used, if they're visible.

Mark clearly which steps were human-directed and which were verified by a human.

**Time box: about 2 hours total.** If you're running over, stop adding features, make sure AC1–AC13 pass or are honestly marked failing, and log what you cut.
