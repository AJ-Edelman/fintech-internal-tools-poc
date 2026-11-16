# fintech-internal-tools-poc

A prototype of three internal tools built on one shared foundation, to show the pattern a fintech
would use to build many of them:

- **Tool 1, refunds:** agents request refunds; small ones are approved automatically, larger ones wait
  for a second person (maker-checker). A database rule keeps pending plus approved refunds within the
  charge amount.
- **Tool 2, KYC review:** a reviewer works a queue of pending customers and approves or rejects each.
  Refunds can be created or approved only for KYC-approved customers (an admin setting, on by default).
- **Tool 3, account limit overrides (`app/limits/`):** a limits agent requests a higher daily limit
  for a customer; a limits approver (never the requester) approves or rejects it. Approval changes the
  limit and sends a message to a fake ledger service.
- **Foundation (`app/foundation/`):** login and sessions, roles and permissions, user management, the
  append-only audit log, a small workflow engine, PII masking, settings, outbound connections
  (`connectors.py`), the shared list screen (`lists.py`), region scope (`scope.py`), and numbered
  migrations. All three tools use it.

Screens show money in dollars; the JSON API stays in integer cents. Refund requests and refund/KYC
decisions take a reason from a dropdown (lists edited by an admin; "Other" plus typed text is always
offered), and queues have quick approve/reject on each row.

All data is synthetic. Stack: Python 3.11, FastAPI, SQLAlchemy, SQLite, Jinja2, pytest, GitHub Actions.

## Prerequisites

Python 3.11 and `make`. `make` looks for `python3.11`, then a pyenv 3.11, then `python3`; override with
`make setup PYTHON=/path/to/python`.

## Clean start

```
make setup     # create .venv, install requirements, apply migrations to data/app.db
make seed      # 20 customers, 40 charges, 8 demo users
make verify    # tests, then the stop-and-restart check
make run       # http://127.0.0.1:8000/login
```

Other targets: `make test`, `make seed-scale` (50,000 refunds in `data/scale.db`), `make test-scale`,
`make access-review` (prints each user's roles and permissions). Tests use temporary databases, never
`data/`. To start over, delete `data/*.db` and run `make setup && make seed`.

## Demo users

All have the password `demo`.

| User | Role | Region | Can |
|---|---|---|---|
| `agent1` | refund_agent | US | see customers (masked) and refunds, request refunds |
| `agent2` | refund_agent | EU | same as `agent1`, EU customers only |
| `approver1` | refund_approver | US | see customers (masked) and refunds, approve or reject |
| `approver2` | refund_approver | EU | same as `approver1`, EU customers only |
| `kyc1` | kyc_reviewer | US | see customers, see full SSN and account on customer detail, decide KYC |
| `kyc2` | kyc_reviewer | EU | same as `kyc1`, EU customers only |
| `limits1` | limits_agent | US | see customers and limit requests, request a higher daily limit |
| `limits2` | limits_approver | US | see customers and limit requests, approve or reject them |
| `admin1` | admin | ALL | users and access, audit log, settings, outbound messages and retry |

Seeded customers 1 to 10 are US and 11 to 20 EU. KYC: 6 to 8 (US) and 13 to 17 (EU) pending, 18 to 20
rejected, the rest approved. Each customer has two charges; customers 1 to 10 have one
over $1,000. Every customer starts with a daily limit of $5,000.00.

## Demo walkthrough

1. Log in as `agent1`. Request $750.00 on a charge of customer 1 (amount in dollars, reason from the
   dropdown): it is `pending_approval`. Request $500.00 on a different charge with no refunds yet: it
   is approved by `system`. (The seed already put refunds on charges 1, 3 and 5; use other charges.)
2. Log in as `agent2` (EU) and request a refund on a charge of customer 13 (KYC pending): rejected
   with 422.
3. **Outbound connections.** Log in as `approver1`, open the approval queue and approve the $750
   request with a reason (quick approve on the row, or from the refund page). The refund page shows
   the audit history and the payout delivery status (`sent`); the $500 refund approved by `system`
   also sent one. As `admin1`, open **Outbound messages** (`/admin/connectors`): every message with
   its connector, record, status, attempts and last error, filterable by status. A message is `failed` after 3 attempts;
   the admin can retry it with a reason (audited), and the receiver still gets it only once. The
   demo's fake services do not fail on their own, so the failure and retry path is shown by the tests
   (AC16).
4. **Shared lists.** On customers, refunds, the approval queue, the KYC queue, the audit log, outbound
   messages and limit requests: search, sort by any sortable column in either direction, filter, and
   page, all on the server with an exact total. Queues show how long each item has waited and list
   the oldest first. Searching a full SSN as `agent1` finds nothing.
5. **Region scope.** As `agent2` (EU), the customer and refund lists show only EU customers and their
   counts; opening a US customer or refund, e.g. `/customers/1`, returns 404, not 403. `approver2`
   cannot decide a US refund (404). `admin1`'s access review shows the region of each assignment.
6. **KYC.** Log in as `kyc1` (US): the KYC queue lists only the US pending customers 6 to 8. Log in
   as `kyc2` (EU), open the KYC queue (masked; only EU customers 13 to 17), open customer 13 (full values, and the view is audited), approve with a reason.
   `agent2` can now request a refund for customer 13.
7. **Tool 3, limit overrides.** Log in as `limits1`, open the limit request form, and request a new
   daily limit above $5,000.00 (at most $50,000.00) for a KYC-approved US customer, with a reason:
   it is `pending_approval`; a second pending request for the same customer is refused. Log in as
   `limits2`, open the limits queue, approve with a reason: the customer's limit changes, the detail
   page shows the history, and a ledger message is `sent` (visible to `admin1` under Outbound
   messages). `limits1` cannot approve their own request.
8. Log in as `admin1`: on settings change the auto-approve limit (dollars, max $750, no reason needed;
   the audit event records who, when, old and new value), the session timeout, the KYC-before-refund
   switch, the maximum refund age and the reason lists. Add a user, change roles and region,
   deactivate or reactivate a user (an admin cannot change their own access and the last admin
   stays). Read the audit log and the access review.

## Which test covers each AC

| AC | Test |
|---|---|
| AC1 | `make setup && make seed && make verify`; login page: `tests/test_pages_and_paging.py::test_login_page_and_login_form_flow` |
| AC2 | `tests/test_refund_flow.py::test_ac2_*` |
| AC3 | `scripts/verify_restart.py` (run by `make verify`) |
| AC4 | `tests/test_permissions.py::test_ac4_*` |
| AC5 | `tests/test_permissions.py::test_ac5_*` |
| AC6 | `tests/test_cap_and_audit_sql.py::test_ac6_*` |
| AC7 | `tests/test_kyc.py::test_ac7_*`, `tests/test_pages_and_paging.py::test_pii_is_masked_for_refund_roles_everywhere` |
| AC8 | `tests/test_cap_and_audit_sql.py::test_ac8_sql_update_and_delete_on_audit_event_fail_and_leave_the_row_unchanged` |
| AC9 | `tests/test_refund_flow.py::test_ac9_history_can_be_rebuilt_from_audit_event_alone` |
| AC10 | `tests/test_kyc.py::test_ac10_*` |
| AC11 | `tests/test_scale.py` (`make seed-scale && make test-scale`); small version `tests/test_pages_and_paging.py::test_ac11_small_paging_with_status_filter` |
| AC12 | `tests/test_permissions.py::test_ac12_admin_lists_role_assignments_others_403_no_session_401` |
| AC13 | `.github/workflows/ci.yml` runs `make test` on every push |
| AC14 | `tests/test_kyc.py::test_ac14_database_at_001_upgrades_to_002_with_every_row_intact` |
| AC15 | `tests/test_connectors.py::test_ac15_*` |
| AC16 | `tests/test_connectors.py::test_ac16_failure_three_audited_attempts_then_authorized_retry` |
| AC17 | `tests/test_connectors.py::test_ac17_*` |
| AC18 | `tests/test_lists.py::test_ac18_customers_refunds_and_kyc_lists_small`; 50,000 rows: `tests/test_scale.py::test_ac18_*` |
| AC19 | `tests/test_lists.py::test_ac19_agent_searching_a_full_ssn_gets_no_match_and_no_ssn` |
| AC20 | `tests/test_scope.py::test_ac20_*` (refunds, KYC), `tests/test_limits.py::test_ac20_tool3_eu_users_cannot_see_or_act_on_us_customers` |
| AC21 | `tests/test_migration_004.py::test_ac21_*` |
| AC22 | `tests/test_limits.py::test_ac22_*` |
| AC23 | `tests/test_limits.py::test_ac23_denials` |
| AC24 | `tests/test_lists.py::test_ac24_*` |

Product-feedback changes (dollars, reason dropdowns, quick decisions, user management, settings,
migration 006) are covered by `tests/test_feedback_forms.py`, `test_feedback_lists.py`,
`test_feedback_admin.py` and `test_feedback_settings.py`; queue waiting time by
`tests/test_lists.py::test_queues_show_waiting_time_and_sort_oldest_first`.

## How to add tool N

These are the steps tool 3 (limit overrides) followed. It added one package, `app/limits/`
(`workflow.py`, `routes.py`), three templates, one migration and its roles; the only foundation file
it changed was `app/main.py`.

1. **Migration:** add `migrations/00N_name.sql` (tool 3: `004_limit_overrides.sql`). Change the schema
   in place; `make setup` applies it to an existing database and records it in `schema_migration`.
   Put hard rules in the database too (tool 3: one pending request per customer, enforced by SQL).
2. **Roles and permissions:** add them to the one mapping in `app/foundation/permissions.py`, with
   plain labels (tool 3: `limits_agent`, `limits_approver`, `limit:*`).
3. **Workflow:** create `app/<tool>/workflow.py` and declare a `Workflow` with its states and
   `Transition`s (permission and guards each; `customer_of` for region scope; `sends=` for outbound
   messages). The engine checks scope and permission, runs the guards, changes the state, writes the
   audit event and records any outbound message in one transaction. See `app/limits/workflow.py`.
4. **Routes:** create `app/<tool>/routes.py`. Every route takes `Depends(require("<permission>"))`;
   a test fails if one does not. Declare list screens with `lists.register(ListSpec(...))` and render
   them with `lists.render`; a test fails if a list route bypasses the shared list. Add `NAV` entries and templates
   under `app/templates/` (tool 3: `limit_form.html`, `limits_list.html`, `limit_detail.html`).
5. **Register:** import the router and add it to `TOOL_ROUTERS` in `app/main.py`.
6. **Cross-tool rules:** if needed, add a guard to another tool's transitions (tool 2 added
   `guard_customer_kyc_approved` to refund `request` and `approve`; tool 3 checks KYC in its own guards).
7. **Tests and seed:** add tests per criterion and update `app/seed.py` (users) and `tests/conftest.py`
   setup data.

## Limitations

- No real SSO or MFA. Login is a stub with one shared demo password.
- No CSRF tokens.
- One admin can change the auto-approve limit (up to $750) and the other settings without a second
  approver or a reason (the audit event records who, when, old and new value).
- No production hosting, encryption at rest or backups.
- No retention or disposal of data.
- The audit log is append-only for the app, but not tamper-proof against whoever controls the
  database file (they can drop the triggers).
- KYC has no claim/lock, escalation or documents. It is a review workflow only.
- No data was migrated from an existing platform.
- The scale test shows correct paging, not performance.
- Free text (refund and decision reasons) is redacted by pattern: `NNN-NN-NNNN` and runs of 8 or more
  digits. An SSN or account number typed with other separators (for example `900 12 3456`) is not
  caught.
- The refund cap is enforced by SQLite triggers; someone with the database file can remove them.
- The connection layer talks only to fake services (`fake://payments`, `fake://ledger`); no real third
  party is called.
- Delivery runs in the app process (after each request), not in a separate worker.
- Regions are a single flat scope (`US`, `EU` or `ALL`), not a hierarchy.
- Non-engineers cannot build or change a tool without code.
