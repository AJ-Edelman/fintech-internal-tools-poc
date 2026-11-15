# Step 1: Constraints, Assumptions, Needs, Pain Points

Status key: **Accepted** (taken as given) · **Confirmed** / **Refuted** (by sourced research) · **Open** (needs client data) · **Unresolvable** (state both cases).
Sources: [`research/RESEARCH.md`](./research/RESEARCH.md) (S1–S14). Last updated 2026-11-15.

## Fixed constraints
- Series C fintech, ~60 engineers. Regulated workloads: KYC/AML (PII), refunds (money movement), feature flags (production change control).
- $250k/yr on the internal-tool platform (Power Apps used as the proxy). 3 live apps, 10+ planned.
- The VP's claims, tested separately: (a) Devin can build these tools, (b) license cost is saved, (c) full customization control.

## Assumption register

| # | Assumption | Status | Evidence / note |
|---|---|---|---|
| A1 | The platform behaves like Power Apps | Accepted | Proxy per the brief |
| A2 | Licensing is per **end user**, not per builder | Confirmed (model) | Premium is $20/user/mo, unlimited apps per user [S1]; building is free, running needs paid licenses [S1]. The cost driver is ops headcount using apps, not engineers. |
| A3 | Who builds today: engineers or ops citizen developers | Unresolvable | Both cases are stated. If ops builds, moving to code shifts work onto engineering. |
| A4 | What makes up the $250k | Open, and **flagged** | At list price, $250k ÷ $240/user/yr ≈ **1,040 Premium users** [S1]. That likely exceeds the headcount of a company with 60 engineers, so the $250k probably also covers Power Automate [S2], Dataverse capacity add-ons [S1], per-app licenses [S2], partner/implementation fees, or an M365/Dynamics bundle [S3]. The **avoidable** cash depends on this split. |
| A5 | Each new tool increases license cost | **Refuted (for per-user Premium)** | Premium covers unlimited apps per licensed user [S1]. A new tool for already-licensed users costs ~$0 in licenses; only new users or new capacity add cost. "Save money as we scale" only holds if new tools bring new users or the client is on per-app licensing ($5/user/app/mo [S2], no longer sold to new customers in some channels since 2026-01-02 [S3]). |
| A6 | Building in-house = full control | Partially true | Control over code and UX is real. It also moves platform duties to the client (A8). |
| A7 | Devin output can reach production grade for regulated data, with review | Open | Partly tested by the prototype; production viability is **not** established by it. |
| A8 | The client has a cloud, an IdP, and CI/CD to deploy onto | Unresolvable (assumed yes) | **Having infrastructure ≠ free to host and maintain.** Every built app needs a named owning team for runtime, on-call, patching, access reviews, backups, and audit evidence. Today Microsoft owns the platform layer (encryption at rest, geo residency, platform patching [S12]); building moves that layer to the client. |
| A9 | Cash license savings and engineering time are separate ledgers | Accepted (rule) | **Cash:** license avoided (depends on contract term, renewal date, minimums, and user overlap) − hosting − Devin spend − tooling. **Capacity:** engineering hours for build, review, migration, and ownership. They are never netted into one number. |

## Pain-point hypotheses (the VP's stated reasons, stress-tested)
1. **Cost.** Weakened by A5: under per-user licensing the marginal license cost of tools 4–13 may be ~$0. The cash case rests on retiring the *existing* spend (path c), which requires migrating all 3 apps and decommissioning the platform.
2. **Customization control.** Plausible. Known platform ceilings include delegation limits (non-delegable queries only process the first 500 records by default (configurable up to 10,000) and can return silently wrong results [S7]), the Power Fx/canvas UX, and connector-bound integrations. Needs client evidence: which ceilings have they actually hit?
3. **Engineering workflow.** Plausible for an engineering-led team: platform ALM goes through solutions and pipelines [S9], not the team's own git/CI/tests. *Unverified for this client.*
4. **Unstated "why now":** possibly the 10+ new tools, a renewal date, or Devin adoption. The renewal date matters for cash savings timing. `OPEN`

## Value the VP may be under-weighting
- Built-in identity (Entra ID), role-based and column-level security [S5][S6], record auditing [S10], data policies/DLP across connectors [S8], and Managed Environments governance [S4]: all in the license and all things a regulated team must rebuild **and evidence** if it builds.
- Microsoft-operated runtime: encryption, residency, platform patching [S12].
- No-code approvals (Power Automate approvals connector, including sequential approvals [S11]).

## Two questions, kept separate
- **Existing 3 apps:** migration, parallel operation, retraining, data move out of Dataverse. Cash savings only arrive after the platform is fully decommissioned.
- **10+ new tools:** a greenfield choice. Marginal license cost is likely low (A5), so the decision rests on fit, control, speed, and ownership cost.
