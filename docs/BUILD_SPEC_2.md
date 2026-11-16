# Build spec, part 2: connections, shared lists, record scope, tool 3

Continue on the existing implementation branch, on top of whatever is there now. `docs/BUILD_SPEC.md` still applies in full (stack, permission rules, audit rules, PII rules, "never weaken a test", synthetic data only). In `docs/`, read only that file, this file and `BUILD_LOG.md`. Each item below except tool 3 is **foundation** work: build it once in `app/foundation/` and have every tool use it.

## 1. Outbound connections (foundation)
- A tool can declare that a transition sends a message to an external system. The message is recorded in the same transaction as the transition and its audit event, so a state change is never lost or sent without a record.
- Delivery is separate from the request: `pending` → `sent`, or `failed` after 3 attempts. Each message carries an idempotency key, and a resend never produces a second effect at the receiver. Every attempt and outcome is an audit event. Payloads follow the PII rules: no SSN or bank account values.
- The receiver's address is configuration. Ship a fake payments service for the demo and tests (it can be told to fail). No real third party is called.
- A caller with a new permission `connector:read` (given to `admin`) can list messages by status; `connector:retry` (also `admin`) can retry a failed one, with a reason, audited.
- **Refunds use it:** a refund reaching `approved` (by a person or by `system`) sends a payout instruction. The refund page shows the delivery status.

## 2. Shared list screens (foundation)
- One list component that a tool configures by declaring columns, which are searchable, which are sortable, and which filters exist. Search, sort, filter and paging all run on the server, and the total count is always exact.
- Every list and queue in every tool uses it: customers, refunds, the refund approval queue, the KYC queue, the audit log, connector messages, tool 3.
- Queues show how long each item has waited and sort oldest first by default.
- Search must never match on, or reveal, an unmasked SSN or bank account for a caller without `pii:read`.

## 3. Record-level access (foundation)
- Migration 003 adds a `region` to `customer` (`US` or `EU`; existing rows become `US`) and a region to each role assignment (`US`, `EU` or `ALL`).
- A caller sees and acts only on records whose customer is in a region they hold for the permission in use. This applies to lists, counts, detail pages, search results and every transition. Out-of-scope records return 404, not 403, and are not counted.
- `admin` permissions are `ALL`. The access review shows the region of each assignment.
- Seed: `agent1`, `approver1`, `kyc1` are `US`; `agent2` is `EU`; add `approver2` (`EU`). Customers are split across both regions.

## 4. Tool 3: account limit overrides (a tool the client does not have)
Record the start time before touching it and the time it first passes. Build it only from foundation pieces; log every foundation file you had to change and why.
- Migration 004 adds `customer.daily_limit_cents` (default 500000) and a `limit_override` table.
- Roles: `limits_agent` (`customer:read`, `limit:read`, `limit:request`) and `limits_approver` (`customer:read`, `limit:read`, `limit:approve`). Seed `limits1` and `limits2` (`US`).
- A `limits_agent` requests a new daily limit for a customer, with a reason. Always `pending_approval`; there is no automatic approval. A `limits_approver` approves or rejects with a reason; nobody decides their own request.
- Rules: the customer's `kyc_status` must be `approved` to request or approve; the requested limit must be above the current one and at most 5000000 cents; one pending request per customer at a time (enforced in the database, including against direct SQL).
- On approval, `customer.daily_limit_cents` changes in the same transaction, and a message is sent through the connection layer to a fake ledger service.
- Pages: request form, queue and detail with history, all from the shared pieces.

## Acceptance criteria (automated, through HTTP unless marked; all existing criteria must still pass)
| # | Criterion |
|---|---|
| AC15 | Approving a refund creates exactly one message; the fake payments service receives it once, and the refund shows `sent` |
| AC16 | With the service failing, the message is `failed` after 3 attempts, each attempt is audited, and the refund stays `approved`. After the service recovers, an admin retries: `sent`, received once. A non-admin retry gets 403 |
| AC17 | If the transition fails (for example over the cap, or self-approval), no message exists. (SQL) no message row exists without its audit event |
| AC18 | On the customers, refunds and KYC lists: search returns exactly the matching rows; sorting by two different columns in both directions is correct; the count matches. A small and a 50,000-row version, as AC11 |
| AC19 | An agent searching by a full SSN gets no match and no SSN in the response |
| AC20 | `agent2` (EU) cannot see, count, search or request a refund on a US customer's records (404). `approver2` cannot decide a US refund. Tests cover refunds, KYC and tool 3 |
| AC21 | (migration) A database at 002 with data upgrades to 004 with every row intact, all customers `US`, and existing assignments still working |
| AC22 | Tool 3: request → `pending_approval` → approved by another user → the customer's limit changed, one audit event per step, one ledger message `sent` |
| AC23 | Tool 3 denials: self-approval 403; a refund agent requesting 403; a second pending request for the same customer 422 (and fails by direct SQL); a customer not KYC-approved 422; a limit at or below the current one, or above the maximum, 422 |
| AC24 | A test walks every list route and fails if one does not use the shared list component |

## README and build log
- README: add the new users, a walkthrough step for each item above, the AC-to-test table, and update "how to add tool N" to match what tool 3 actually took. Limitations must add: the connection layer talks only to fake services; delivery runs in the app process, not a separate worker; regions are a single flat scope, not a hierarchy; non-engineers cannot build or change a tool without code.
- Build log, same rules as before, plus: start and end time of each of the four items; for tool 3, lines added per directory, every foundation file changed and why, and `git diff --stat` from the commit before tool 3 to the commit where it passes. Tag `tool3-done`.

## Time limit: 55 minutes for this spec, hard
Stop feature work at minute 45. Order: 1, 2, 3, then 4; tool 3 must start by minute 30. If you are behind at minute 30, cut item 3 (log it) and build tool 3 without regions. Never cut tool 3, the connection layer or their tests. At 55, stop and report the real status.
