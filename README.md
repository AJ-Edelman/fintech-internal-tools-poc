# fintech-internal-tools-poc

A prototype of two internal tools built on one shared foundation, to show the pattern a fintech
would use to build many of them:

- **Tool 1, refunds:** agents request refunds; small ones are approved automatically, larger ones wait
  for a second person (maker-checker). A database rule keeps pending plus approved refunds within the
  charge amount.
- **Tool 2, KYC review:** a reviewer works a queue of pending customers and approves or rejects each.
  Refunds can be created or approved only for KYC-approved customers.
- **Foundation (`app/foundation/`):** login and sessions, roles and permissions, the append-only audit
  log, a small workflow engine, PII masking, settings, and numbered migrations. Both tools use it.

All data is synthetic. Stack: Python 3.11, FastAPI, SQLAlchemy, SQLite, Jinja2, pytest, GitHub Actions.

## Prerequisites

Python 3.11 and `make`. `make` looks for `python3.11`, then a pyenv 3.11, then `python3`; override with
`make setup PYTHON=/path/to/python`.

## Clean start

```
make setup     # create .venv, install requirements, apply migrations to data/app.db
make seed      # 20 customers, 40 charges, 5 demo users
make verify    # tests, then the stop-and-restart check
make run       # http://127.0.0.1:8000/login
```

Other targets: `make test`, `make seed-scale` (50,000 refunds in `data/scale.db`), `make test-scale`,
`make access-review` (prints each user's roles and permissions). Tests use temporary databases, never
`data/`. To start over, delete `data/*.db` and run `make setup && make seed`.

## Demo users

All have the password `demo`.

| User | Role | Can |
|---|---|---|
| `agent1`, `agent2` | refund_agent | see customers (masked) and refunds, request refunds |
| `approver1` | refund_approver | see customers (masked) and refunds, approve or reject |
| `kyc1` | kyc_reviewer | see customers, see full SSN and account on customer detail, decide KYC |
| `admin1` | admin | access review, audit log, auto-approve limit |

Seeded customers 1 to 12 are KYC-approved, 13 to 17 pending, 18 to 20 rejected. Each customer has two
charges; customers 1 to 10 have one over $1,000.

## Demo walkthrough

1. Log in as `agent1`. Request $750.00 on a charge of customer 1: it is `pending_approval`. Request
   $500.00 on a different, unused charge: it is approved by `system`.
2. Still as `agent1`, request a refund on a charge of customer 13 (KYC pending): rejected with 422.
3. Log in as `approver1`, open the approval queue, approve the $750 request with a reason. The refund
   page shows the audit history.
4. Log in as `kyc1`, open the KYC queue (masked), open customer 13 (full values, and the view is
   audited), approve with a reason. `agent1` can now request a refund for customer 13.
5. Log in as `admin1`: change the auto-approve limit (max $750, reason required), read the audit log,
   and open the access review.

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

## How to add tool N

These are the steps tool 2 followed.

1. **Migration:** add `migrations/00N_name.sql`. Change the schema in place; `make setup` applies it to
   an existing database and records it in `schema_migration`.
2. **Permissions:** if the tool needs new ones, add them to the one mapping in
   `app/foundation/permissions.py`. (Tool 2's were already there.)
3. **Workflow:** create `app/<tool>/workflow.py` and declare a `Workflow` with its states and
   `Transition`s (permission and guards each). The engine checks the permission, runs the guards,
   changes the state and writes the audit event in one transaction. See `app/kyc/workflow.py`.
4. **Routes:** create `app/<tool>/routes.py`. Every route takes `Depends(require("<permission>"))`;
   a test fails if one does not. Add a `NAV` entry and templates under `app/templates/`.
5. **Register:** add the router to `TOOL_ROUTERS` in `app/main.py`.
6. **Cross-tool rules:** add a guard to the other tool's transitions (tool 2 added
   `guard_customer_kyc_approved` to refund `request` and `approve`).
7. **Tests and seed:** add tests per criterion, add the new module to the role-name test, and update
   `app/seed.py` and `tests/conftest.py` setup data.

## Limitations

- No real SSO or MFA. Login is a stub with one shared demo password.
- No CSRF tokens.
- One admin can change the auto-approve limit (up to $750) without a second approver.
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
