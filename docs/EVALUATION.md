# Evaluation and recommendation

For the client's VP of Engineering. Sources are in [`research/RESEARCH.md`](./research/RESEARCH.md) (S1–S31),
assumptions in [`ASSUMPTIONS.md`](./ASSUMPTIONS.md) (A1–A11), measurements in `BUILD_LOG.md` on the build branch.
Each line is marked **measured** (observed in the prototype), **sourced**, or **assumed** (needs client data).

## Recommendation

**Path b, as a pilot of delivery and customization, not as a way to save the license.** Keep the platform
and the three live tools. Build the next one or two new tools in code with Devin, on the stack the team
already runs. Set stop conditions before starting (below), and decide the rest at the license renewal.

The prototype shows the build is technically feasible. It does not show that it is cheaper. Under
per-user licensing, path b is expected to save about $0 in licenses while the same staff still use the
three existing apps (sourced, S1; A5), so it has to earn its place on fit, control and delivery speed.

## The three paths

Transition costs are one-time; steady-state costs are annual. No dollar totals are given because the two
largest inputs (the avoidable share of the $250k and the client's engineering cost) are unknown.

| | a. Stay and optimize | b. Build selected new tools, keep the platform | c. Replace the platform for all 13 tools |
|---|---|---|---|
| License avoided | None, or a little if a license audit finds unused seats (assumed) | About $0 while the same users keep Premium for the three live apps. May avoid growth for users who would only need new tools (assumed, A5) | Up to the avoidable share of $250k, and only after the last app has moved and the platform is switched off |
| Transition cost | Low: a license and usage audit | A production foundation (engineer-weeks, not measured), then spec, build and review per tool | Path b's cost, plus migrating three live tools and their data, parallel running of both systems, retraining. Not measured |
| Steady-state cost | The license, plus the platform administration the client already does | The license **and** hosting, Devin, and a team owning the new tools | Hosting, Devin, and a team owning all 13 tools and their compliance evidence |
| What it buys | No change in ownership; non-engineers can keep building (S19) | Code-level control for the tools that need it, and real numbers for path c | The cash saving, if one exists, and full control |
| Main risk | Platform limits, if they are real for this team (unknown) | Two systems to run; cost is added, not removed | Largest and least reversible; rests on numbers nobody has yet |

Path c cannot be assessed today. Path b is the cheapest way to get the numbers that would assess it, and
path a's first step (the license audit) is needed in every case.

## The three claims

| Claim | Finding |
|---|---|
| "Devin can build these tools" | **Yes for the application layer** (measured). Three tools on one foundation: shared customer data, permissions by role, record and column, maker-checker approvals, append-only audit, outbound connections. Not shown: everything in "What the prototype does not establish" |
| "We save the license cost" | **Unproven.** Premium licensing is per user with unlimited apps (sourced, S1), so 10 more tools for the same users add about $0 in licenses. At list price $250k is about 1,040 Premium users (arithmetic, S1). We do not know the number of operations, compliance and support users, the contract price, or what else the bill covers (A4), so we cannot say how much is avoidable |
| "Full customization control" | **True for code, screens and deployment. False for coupling.** The shared foundation that makes each new tool cheap also means a change to it touches every tool. Building changes who owns that problem, not whether it exists (sourced, A10). The platform is also more open than "low-code" suggests: custom connectors wrap any REST API ([Microsoft Learn, custom connectors](https://learn.microsoft.com/en-us/connectors/custom-connectors/)), and plug-ins and Azure functions run custom code (sourced, S19, S20) |

## Cost, on two separate ledgers

**Cash.** Annual saving = license actually avoided − hosting − Devin (seats and usage) − tooling. The
first term needs the contract: what the $250k covers, the renewal date, minimums, and whether the same
users need the platform for anything else.

**Engineering capacity.** This is time, not cash, and is not netted against the license. Build cost has
three layers, and only the first is measured.

| Layer | Estimate | Basis |
|---|---|---|
| 1. This prototype | About 2 hours of planning and research (the author working with Devin), 94 minutes of active Devin build time (41 for the first build, then 14, 27 and 12 for feedback changes and two follow-up specs; time between sessions is excluded), and 30 minutes of reviewing the app: roughly 4 hours end to end. Devin usage (ACUs) was not captured | Hours are the author's estimate; build minutes are measured from the build log |
| 2. A production foundation | Not measured. Needs SSO and MFA, hosting, backups, encryption, retention, monitoring and real integrations. Expect engineer-weeks, to be sized by the client's own team | Assumed |
| 3. Each further tool | A written spec, a Devin build, independent checks and human review. Tool 2 took 2 minutes to a first passing run and 28 with checks and fixes; tool 3 took 2 minutes (about 100 and 314 lines of tool code, with one foundation file changed for tool 3) | Measured, and a low end: both tools were simple and synthetic |

**How to read this.** More than half of the prototype's time went to planning, research and review, not to
build minutes. That ratio is the useful finding: the cost of each further tool will be set by how long
it takes to specify and review, and by layer 2, not by how fast the code is written. Two data points on
synthetic tools do not price tools 4 to 13, so this is a range with stated assumptions, not one number.

**Break-even for path c.** Building is cheaper in steady state only if

> avoidable license > hosting + Devin + tooling + (hours to own the built tools − hours spent today administering and maintaining the Power Apps tools) × loaded hourly cost

Every term on the right, and the avoidable share on the left, must come from the client. The comparison
is the extra effort over today's, not the total. The pilot exists to measure the hours.

## Maintenance burden

Responsibility is shared on both sides, in different places.

| | On Power Apps | On a custom build |
|---|---|---|
| Provider runs | The platform: hosting, platform patching, encryption at rest, automatic backups (sourced, S12, S23) | Whatever managed services the client chooses. A managed database typically covers backups, encryption at rest and engine patching (assumed; depends on the client's cloud) |
| Client still owns | Security roles, data-loss policies, environments, connector credentials, the apps and flows themselves, access reviews (sourced, S5, S8) | All of the application: code, dependencies, sign-in integration, deployment, monitoring, on-call, access reviews, audit evidence (A8) |

So a build does not move "everything" to the client, but it does move the application runtime, its
security and its evidence. Devin can do much of the routine work (upgrades, test fixes, new tools from
the template), but someone still reviews and is accountable.

## Security

- **Shown in the prototype:** server-side permission checks on every route, PII masked by role with
  audited reveals, region-scoped records, CI on every push. Enforced in the database by SQLite triggers
  as well as in the application: the refund cap, no self-approval, the KYC rule for refunds, the $750
  limit cap, and the append-only audit log (measured: direct database writes were refused).
- **What the checks caught:** fresh Devin sessions with no build context found two real SSN leaks into
  the audit log, and a later review found admin changes that weaken controls with no reason recorded.
  Both are fixed and covered by tests. Generated code needs independent review; that review worked here,
  and it is a standing cost.
- **Not shown:** MFA, encryption, retention and disposal, tamper-proofing against whoever controls the
  database. These are requirements under the rules most likely to apply (S26–S30, applicability assumed).

**Devin's own footprint.** Devin is a new vendor with access to source code, and that is part of the decision.

| Item | What to settle |
|---|---|
| Recurring cost | Seats plus usage on self-serve plans, usage at contract rates on Enterprise (sourced, S13). It belongs in the cash ledger. The prototype's usage was not captured |
| Repository access | Scoped through the GitHub App (sourced, S14). Limit it to the internal-tools repositories, with branch protection and human approval before merge |
| Credentials | Sessions can use whatever secrets they are given. Give test credentials only; production deploys run from CI, not from a session |
| Data | The prototype used synthetic data only. Customer PII should not enter a session; this needs a rule and a check, not an assumption |
| Vendor review | SOC 2 Type II and the training-data terms are published (sourced, S14). The client's own vendor review still applies |

## Opportunity cost

Every hour spent owning internal tools is an hour not spent on the product. The one thing the platform
offers that code does not is that non-engineers can build and change tools (sourced, S19). If operations
staff build tools today, moving to code moves that work onto engineers (A3, unknown). Power Apps also has
AI-assisted building, so the choice is not "AI versus no AI"; it is who owns the output.

## What the prototype does not establish

Real SSO or MFA; production hosting, backups, encryption or on-call; real third-party integrations (the
payments and ledger services are fakes); document attachments; retention; non-engineer authoring;
migration of existing data; the cost of tools 4 to 13. Nothing was run with real data.

How it was checked: automated tests and direct API and database calls on the build branch, and the author
tested the running prototype by hand.

## Risks

| If they build | If they stay |
|---|---|
| The foundation becomes a product with one owner; if that owner leaves, every tool on it is exposed | In canvas apps, a query that cannot be delegated reads only the first 500 records by default (10,000 at most) and returns wrong results without an error (S7). Delegable queries and model-driven apps are not affected |
| Compliance evidence for the built tools now has to be produced in-house | Cost grows with operations headcount at $240 per user a year at list (S1) |
| License saving turns out smaller than expected, or zero | Platform solutions also couple apps together (S15–S17) |
| A new vendor (Devin) with source access | Custom integrations are possible but go through custom connectors or plug-ins, which are code the team must also own |

## Next steps

**In every case (one to two weeks, no engineering).** Get the license breakdown and renewal date, and
count active users against paid seats. List which platform limits the team has actually hit.

**If they stay on Power Apps (path a).**
1. Remove unused seats and capacity found by the audit.
2. Fix the limits that are real, starting with any non-delegable queries on lists that have outgrown the row limit (S7).
3. Where Devin fits: the code-side pieces the platform still needs, such as custom connectors to internal APIs, plug-ins, automated tests, and data or migration scripts. This is a smaller role, and Devin may not be needed at all.

**If they run the pilot (path b).**
1. Pick one or two new tools the platform handles badly (large data sets, custom integrations). Leave the three live tools alone.
2. Apply the prototype's patterns on the stack, sign-in and database the team already runs. The prototype's own foundation is a reference, not something to deploy.
3. Name an owning team before the first build.
4. Measure for one quarter: human hours to specify and review each tool, incidents, upkeep hours, and Devin cost.
5. Where Devin fits: build each tool from a written spec, run independent checks in fresh sessions, keep dependencies and tests current, and build independent tools in parallel. Engineers write the specs, review, and own production.

**Stop or pause the pilot if any of these happens.**
- No team will own the built tools in production.
- Human review hours for the second tool are not clearly lower than for the first.
- A security or data defect reaches production that the independent checks missed.
- Production groundwork (sign-in, hosting, backups, monitoring) is not finished within the time the team budgets for it up front.
- The license breakdown shows little of the $250k is avoidable **and** the team has hit no real platform limit. Then path a is the answer.

**Decide at renewal.** Consider path c only if the avoidable license exceeds the measured ownership cost
in the break-even formula above.
