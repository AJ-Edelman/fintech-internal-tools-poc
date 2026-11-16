# Build spec, part 3: review fixes

`BUILD_SPEC.md` and `BUILD_SPEC_2.md` still apply, with one recorded change: **the product owner decided that changing the auto-approve limit needs no reason.** That stays as built. No other reason requirement may be dropped. All existing tests must still pass; never weaken one.

## Fixes
1. **Reasons on changes that weaken a control.** Changing `refund_requires_kyc`, `max_refund_age_days`, or a user's roles, region or active status requires a non-blank reason (API and form; 422 without one). The reason is stored on the audit event, redacted like other free text. The auto-approve limit, session timeout and reason lists stay as they are.
2. **Rules at the data layer.** Migration 007 adds triggers so these hold against direct SQL too: (a) a refund or a limit override cannot be moved to `approved` or `rejected` with `decided_by` equal to `requested_by`; (b) a refund cannot be inserted, or moved to `approved`, for a customer whose `kyc_status` is not `approved`, while the `refund_requires_kyc` setting is true; (c) the `auto_approve_limit_cents` setting cannot hold a non-integer, a negative value or a value above 75000. The `system` auto-approval must still work.
3. **Demo seed.** `kyc1` (US) must have at least 3 US customers awaiting KYC review, and the EU reviewer case must still be demonstrable. Keep the counts the tests and README rely on correct; update the README walkthrough so it no longer needs the workaround of adding an EU reviewer first.
4. **KYC queue API** honours `sort` and `dir` like every other shared list.
5. **Build log.** Add an entry for the product-feedback block between the end of the first build (01:30 UTC) and the start of BUILD_SPEC_2 (02:16 UTC): when work actually started and stopped, what was asked, what changed, which tests changed and why (including `test_ac2_limit_change_needs_no_reason...`). Then add a table of every work block with start, end and minutes, and two totals: minutes of active work and wall-clock minutes from 00:49. Record only what you observed; if a time is not known, say so.

## Acceptance criteria (automated, through HTTP unless marked)
| # | Criterion |
|---|---|
| AC25 | Each change in fix 1 without a reason gets 422 and changes nothing; with a reason it succeeds and the audit event holds the reason. A limit change without a reason still succeeds |
| AC26 | (SQL) Each direct write in fix 2 fails and leaves the row unchanged; with `refund_requires_kyc` false, 2(b) no longer blocks. Auto-approval by `system` still passes AC2 |
| AC27 | (migration) A database at 006 with data upgrades to 007 with every row intact |
| AC28 | After `make seed`, `kyc1`'s queue has at least 3 customers, all US; an EU reviewer sees only EU ones |
| AC29 | `GET /api/kyc/queue` sorted by two columns in both directions returns the right order |

## README
Update the walkthrough, the AC table, and Limitations: one admin can still make these changes alone (a reason is recorded, there is no second approver); the auto-approve limit needs no reason by product decision; database triggers do not stop someone who controls the database file.

## Time limit: 20 minutes, hard
Stop feature work at minute 15. If behind at minute 10, cut 2(c) first, then fix 4, and log it. Never cut fix 1, 2(a), 2(b), 3 or 5. At 20, stop and report the real status. Tag `review-fixes-done` when AC25 to AC29 pass.
