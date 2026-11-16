# Evaluation and recommendation

For the client's VP of Engineering. Sources are in [`research/RESEARCH.md`](./research/RESEARCH.md) (S1–S31),
assumptions in [`ASSUMPTIONS.md`](./ASSUMPTIONS.md) (A1–A11), measurements in `BUILD_LOG.md` on the build branch.
Each line is marked **measured** (observed in the prototype), **sourced**, or **assumed** (needs client data).

## Recommendation

**Do not cancel the platform, and do not commit to rebuilding all 13 tools. Keep the three live tools where
they are, build the next one or two new tools in code with Devin on a shared foundation, and decide the
rest at the license renewal using the numbers below.**

The prototype shows the build is technically feasible. It does not show that it is cheaper, and the
research suggests the saving is smaller than the $250k headline.

## The three claims

| Claim | Finding |
|---|---|
| "Devin can build these tools" | **Yes for the application layer** (measured). Three tools on one foundation: shared customer data, permissions by role, record and column, maker-checker approvals, append-only audit, outbound connections. Not shown: everything in "What the prototype does not establish" |
| "We save the license cost" | **Unproven, and probably only in part.** Premium licensing is per user with unlimited apps (sourced, S1), so 10 more tools for the same users add about $0 in licenses. At list price $250k is about 1,040 users, more than a 60-engineer company is likely to have, so the bill probably includes other items (assumed, A4). Only the part that goes away when these tools move is a saving |
| "Full customization control" | **True for code, screens and deployment. False for coupling.** The shared foundation that makes each new tool cheap also means a change to it touches every tool. Building changes who owns that problem, not whether it exists (sourced, A10) |

## Cost, on two separate ledgers

**Cash.** Saving = license actually avoided − hosting − Devin usage − tooling. The first term needs the
contract: what the $250k covers, the renewal date, minimums, and whether the same users need the platform
for anything else. Devin usage for the prototype was not visible to the build session and must be read
from the session usage pages.

**Engineering capacity.** This is time, not cash, and is not netted against the license. Build cost has
three layers, and only the first is measured.

| Layer | Estimate | Basis |
|---|---|---|
| 1. This prototype | About 2 hours of planning and research (the author working with Devin), 94 minutes of active Devin build time (41 for the first build, then 14, 27 and 12 for feedback changes and two follow-up specs; 149 on the clock from first to last commit), and 30 minutes of reviewing the app: roughly 4 hours end to end. Devin usage (ACUs) was not captured | Hours are the author's estimate; build minutes are measured from the build log |
| 2. A production foundation | Not measured. Needs SSO and MFA, hosting, backups, encryption, retention, monitoring and real integrations. Expect engineer-weeks, to be sized by the client's own team | Assumed |
| 3. Each further tool | A written spec, a Devin build, independent checks and human review. Tool 2 took 2 minutes to a first passing run and 28 with checks and fixes; tool 3 took 2 minutes (about 100 and 314 lines of tool code, with one foundation file changed for tool 3) | Measured, and a low end: both tools were simple and synthetic |

Migrating the three live tools and their data is not measured and is not part of the recommendation.

**How to read this.** More than half of the prototype's time went to planning, research and review, not to
build minutes. That ratio is the useful finding: the cost of each further tool will be set by how long
it takes to specify and review, and by layer 2, not by how fast the code is written. Two data points on
synthetic tools do not price tools 4 to 13, so this is a range with stated assumptions, not one number.

## Maintenance burden

Today Microsoft patches, backs up, encrypts and hosts the platform (sourced, S12, S23). After a build, a
named team owns all of that for every tool, plus dependency updates, on-call, access reviews and audit
evidence. Having a cloud and an identity provider already does not make this free (A8). Devin can do
much of the routine work (upgrades, test fixes, new tools from the template), but someone still reviews
and is accountable.

**Break-even, as an illustration.** If the whole $250k were avoidable, it pays for roughly one engineer
(assumed loaded cost; use the client's figure). If owning the foundation and 13 regulated tools takes
more than about one engineer's time a year, building costs more than buying before any opportunity cost.

## Security

- **Shown in the prototype:** server-side permission checks on every route, PII masked by role with
  audited reveals, no self-approval, the refund cap, the KYC rule and the $750 limit cap enforced in the database,
  append-only audit enforced in the database, region-scoped records, CI on every push.
- **What the checks caught:** fresh Devin sessions with no build context found two real SSN leaks into
  the audit log, and a later review found admin changes that weaken controls with no reason recorded.
  Generated code needs independent review; that review worked here, and it is a standing cost.
- **Not shown:** MFA, encryption, retention and disposal, tamper-proofing against whoever controls the
  database. These are requirements under the rules most likely to apply (S26–S30, applicability assumed).

## Opportunity cost

Every hour spent owning internal tools is an hour not spent on the product. The one thing the platform
offers that code does not is that non-engineers can build and change tools (sourced, S19). If operations
staff build tools today, moving to code moves that work onto engineers (A3, unknown). Power Apps also has
AI-assisted building, so the choice is not "AI versus no AI"; it is who owns the output.

## What the prototype does not establish

Real SSO or MFA; production hosting, backups, encryption or on-call; real third-party integrations (the
payments and ledger services are fakes); document attachments; retention; non-engineer authoring;
migration of existing data; the cost of tools 4 to 13. Nothing was run with real data.

## Risks

| If they build | If they stay |
|---|---|
| The foundation becomes a product with one owner; if that owner leaves, 13 tools are exposed | Platform ceilings: the delegation cap returns wrong results silently above 500 to 10,000 records (S7); integrations limited to connectors |
| Compliance evidence now has to be produced in-house | Cost grows with operations headcount at $240 per user a year at list (S1) |
| License saving turns out smaller than expected | Platform solutions also couple apps together (S15–S17) |

## Next steps and Devin's role

1. **Get the license breakdown and renewal date** (one week, no engineering). This decides how much cash is at stake.
2. **Pick one or two new tools the platform handles badly** (large data sets, custom integrations). Build them with Devin on a production version of this foundation with a named owning team. Leave the three live tools alone.
3. **Measure for one quarter:** human review hours per tool, incidents, hours of upkeep, and Devin usage.
4. **Decide at renewal:** expand the build only if avoidable license cash exceeds measured ownership cost and the platform ceilings are real for this team.

Devin's role in that pilot: build each tool from a written spec and the foundation template, run
independent checks in fresh sessions, keep dependencies and tests current, and build independent tools
in parallel. Engineers write the specs, review, and own production.
