# Plan of Action

Working plan we step through and iterate on. Source brief: [`PROMPT.md`](./PROMPT.md). Progress checklist: [`TRACKER.md`](./TRACKER.md).

Conventions: plain text = agreed. *Italics = Devin's suggestion or challenge, still open for you to accept or reject.* `OPEN:` = unresolved. `[COLLAB]` = a working session between us before anything is drafted.

---

## Framing decisions (agreed)

- **Neutral starting point.** No default to "stay" or to "build." Switching has a cost, and staying on a known system has real benefits; both are weighed.
- **Two separate questions:** (1) *replacing the 3 existing apps* (migration, parallel operation, retraining, data move) vs. (2) *how to build the 10+ new tools* (greenfield). They have different economics and risks and are never blended into one number.
- **Three paths, one clear recommendation:**
  - **a.** Retain or optimize the current platform.
  - **b.** Build selected new tools with Devin; keep the existing apps on the platform.
  - **c.** Replace the platform's role for this whole portfolio.
  - The Loom lands on one path, with its conditions and what would change it.
- **Compare like with like.** Power Apps is a platform: screens + Dataverse + Power Automate + connectors + Entra identity + governance and admin + hosting. Devin is a development tool, not a runtime. The fair comparison is *Power Apps and its surrounding platform services* vs. *Devin-assisted development + the resulting app stack + infrastructure + integrations + operating ownership*.
- **$250k is taken at face value** (Power Apps is a proxy). The economics use only the **avoidable portion** under each path, not the full $250k.
- **Research is bounded:** no market survey. They already chose the platform. We evaluate only the capabilities relevant to this client.
- **Every research claim is sourced** (URL + access date).
- **The prototype demonstrates a representative development pattern for an internal tool**, not parity and not a platform rebuild. No static dashboards: a narrow working workflow with real persistence and server-side behavior.
- **No generalizing** from one build to "Devin builds 13 apps at this rate." We judge from what instructions were needed, how the build went, time to build, and how much needed fixing.

*Challenges to the framing:*
- *On (b): if licensing is per user and the same ops staff use both old and new tools, path (b) may avoid **almost no** license cost; existing users stay licensed. Then (b)'s case rests on control, fit, and avoiding cost growth for new users, not savings. The license model (per user vs. per app) is the single biggest swing factor for (b). We must state which we assume, and show both.*
- *On (c): the avoidable amount is the full license cost only after the last app is migrated and the platform is decommissioned. Until then the license and the new stack run in parallel (both costs at once). The transition timeline drives (c).*
- *On "taking it at face value" vs. "avoidable portion": these agree. We accept $250k as the total, but the split (users, capacity, other services) is an assumption we state, not a fact we have.*

---

## Step 1: Constraints, assumptions, needs, pain points

- Fixed constraints: ~60 engineers, Series C fintech (regulated: KYC/AML, money movement, PII), $250k/yr, 3 live apps, 10+ planned.
- The VP's three claims, each tested on its own: (a) Devin can build these, (b) license cost is saved, (c) full customization control.
- Pain-point hypotheses: why switch, why now (cost vs. platform limits vs. speed vs. governance).
- **Assumption register**: each entry has the assumption, why it matters, how it's tested, and status (open / confirmed / refuted / unresolvable). Seed entries:

| # | Assumption | Status |
|---|---|---|
| A1 | The platform behaves like Power Apps (proxy) | Accepted |
| A2 | Licensing is per user (end users, mostly ops staff), not per builder | Open: research |
| A3 | Who builds today: engineers vs. ops "citizen developers" | Unresolvable: state both cases |
| A4 | How the $250k splits: licenses vs. Dataverse capacity vs. Power Automate vs. premium connectors | Open: research which apps need which |
| A5 | How cost grows per new tool on the platform | Open: research |
| A6 | Building in-house brings operating ownership (uptime, patches, SSO, audit, SOC 2 evidence) | Open: Step 4 |
| A7 | Devin's output can reach production grade for regulated data, with review | Partially tested by the prototype |
| A8 | The client already has a cloud, an identity provider, and CI/CD to deploy onto | Unresolvable: state it |

**Output:** register (lives in `docs/ASSUMPTIONS.md`) + pain-point list.

---

## Step 2: Research (bounded, sourced)

**2a. The platform beneath the screens.** For each capability: what it does, *which service provides it* (canvas/model-driven apps, Dataverse, Power Automate, connectors, Entra ID, environments/DLP, Managed Environments, ALM pipelines), and *which license tier it requires* (standard vs. premium connectors, Dataverse capacity, add-ons). Capability areas:
- Data modeling and persistence (Dataverse; row/field security).
- Connectors and integration (standard vs. premium; custom connectors to internal APIs).
- Workflow and approvals (Power Automate).
- Identity and permissions (Entra ID, security roles, sharing).
- Governance and admin (environments, DLP policies, audit logging, CoE tooling).
- Deployment and ALM (solutions, pipelines, source control).
- Known limits (e.g. delegation limits, testing, performance, customization ceilings).

**2b. Pricing and unit economics**, enough to back-solve A2/A4/A5 into plausible ranges. Sources: Microsoft pricing pages and Learn docs.

**2c. Devin** (bounded): what it does vs. doesn't do (writes, tests, and maintains code; doesn't host or operate apps), pricing model, security posture and the access it needs. *Pricing must come from current official sources, not memory.*

**2d. Feedback into Step 1:** update the register. Did anything refute a pain point? Did the VP miss any value point (e.g. built-in identity, audit, compliance certifications he'd have to rebuild)?

**2e. Deliverable: the capabilities that matter for this client**, ranked by relevance to a fintech team shipping many internal tools, each marked *replicable easily / replicable with effort / platform-native and hard to replicate*.

**2f. Deliverable: candidate workflow for the prototype**: one bounded workflow that exercises a meaningful subset of 2e.

**Output:** `docs/research/` notes with sources, the capability table, the workflow choice.

---

## Step 3a: Pre-prototype gate

- [ ] Workflow selected from 2f. *Candidate, to confirm after research: a **refund approval workflow with maker-checker**. An agent requests a refund; a refund over a threshold needs a second approver with a different role; the requester can't approve their own refund; every state change is written to an append-only audit log; permissions are enforced on the server. It touches data modeling, workflow and state, role-based permissions, audit, and a real denied-action path, all directly relevant to fintech. The KYC review queue is the alternative.*
- [ ] **Observable acceptance criteria**, written before implementation and checked by running the app or its API, not from screenshots or by reading code. For example:
  - From a fresh clone, the documented startup works with no undocumented steps.
  - The main workflow completes end to end.
  - State persists across a server restart.
  - At least one denied action fails **at the API** (e.g. self-approval returns 403 even when the request skips the UI).
  - Every claimed control is enforced on the backend, verified by a direct API call.
  - Audit entries exist for each state change.
  - Synthetic data only.
- [ ] What the prototype will **not** establish, written down up front (e.g. real identity-provider integration, scale, production hosting, SOC 2 evidence, migrating existing data).
- [ ] Stack chosen (no preference; picked for speed plus a real database). Local run only.
- [ ] Build approach decided. *Challenge: this session is full of planning context, so it isn't how an engineer at the client would brief Devin. Suggestion: write a short build spec (`docs/BUILD_SPEC.md`) and build from it, ideally in a fresh Devin session, so "what instructions were needed" can be inspected and is representative. `OPEN:` your call.*

## Step 3b: Prototype (~2h; you keep the clock)

- Build the workflow from 3a with Devin.
- **Evidence log** (`docs/BUILD_LOG.md`), internal. Each entry tagged **Devin built** / **you directed** / **you verified**, with links to commits, Devin sessions, and PRs. Also logged: failures, rework, and instructions that had to be clarified.
- **Verification** against the 3a criteria, run as reproducible commands (test script and/or curl calls) and checked in, so reviewers can re-run them.
- **README** (non-negotiable): what it does, prerequisites, a clean-start check, how to run, seed data, demo users and roles (synthetic), how to verify, limitations / what it doesn't establish, reviewer access.

---

## Step 4: Evaluate

Each lens gets its own explicit section:
1. **Build cost**: initial implementation and review.
2. **Migration cost** (only for paths b/c on the existing apps): migration and parallel operation.
3. **Production hardening**: identity, integrations, security review, deployment.
4. **Run cost**: hosting, tooling, Devin usage.
5. **Maintenance burden**: ongoing ownership, dependency updates, incidents, change requests.
6. **Security implications**: what moves from Microsoft's shared-responsibility model to the client; Devin's own access footprint.
7. **Opportunity cost**: engineering capacity diverted from customer-facing work.

Cost rules:
- Transition (one-time) and steady-state (annual) costs are separate.
- Avoidable license cost is computed per path.
- **No double counting:** each engineering hour is counted once, either at loaded cost *or* as displaced roadmap capacity, never both. *Suggestion: put hours at loaded cost in the dollar model; describe opportunity cost qualitatively (which roadmap work slips) using the same hours.*
- Inputs are parameterized ranges, not point estimates.

**Prototype ≠ production.** Explicitly list what the prototype showed vs. what it can't show. Name the largest unresolved economic and operational assumptions.

## Step 4b: Recommendation (distinct output, `docs/RECOMMENDATION.md`)

- Chosen path (a / b / c).
- Conditions under which it holds.
- What would change it (specific triggers, e.g. "if licensing is per app, not per user").
- Next steps in either direction, and where Devin fits in each.

---

## Step 5: Loom: decide content, then script `[COLLAB]`

1. **Content decisions first** `[COLLAB]`: for each of the 5 required topics, agree on the 1-3 points we make, the evidence behind them, and what we cut. Recorded in `docs/LOOM_OUTLINE.md`.
   1. The most important aspects of Power Apps.
   2. How Devin helps if they build, shown through the prototype.
   3. What's replicable, what isn't, and where the risk lies.
   4. The build-vs-buy recommendation and why.
   5. What's next in either direction, and where Devin fits.
2. **Timestamped script**, 5:00 max (~650-700 spoken words, including the demo segment).
3. Dry-run timing check. Recording happens after the one-pager.

## Step 6: Key Decisions one-pager `[COLLAB]` (for Cognition, 1 page)

- It is a design rationale, not a findings summary or a process diary.
- Candidate sections: what was built; why this scope; how the system is structured; which alternatives and tradeoffs mattered; what the design does not establish.
- Structure decided together; the final wording is yours.

## Step 7: Record the Loom, final audit

- Record after the one-pager.
- Final line-by-line audit against `PROMPT.md` via `TRACKER.md`.
