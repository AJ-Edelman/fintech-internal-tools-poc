# Plan of Action

Working plan we step through and iterate on. Source brief: [`PROMPT.md`](./PROMPT.md). Progress checklist: [`TRACKER.md`](./TRACKER.md).

Conventions: plain text = agreed plan. *Italics = Devin's suggestion or challenge, for you to adopt, reject, or push back on.* `OPEN:` = unresolved question.

---

## Step 1: Constraints, assumptions, client needs, pain points

**Goal:** Take the VP at his word, but separate what he *said* from what he *needs*, and write every assumption down so research can confirm or kill it.

**Fixed constraints (from the brief):**
- About 60 engineers, Series C fintech (regulated: KYC/AML, money movement, PII).
- $250k/yr platform spend. 3 live apps (KYC review queue, refunds dashboard, feature-flag admin). 10+ more planned.
- The stated goals are three separate claims, each tested on its own: (a) Devin can build these, (b) the license cost goes away, (c) the team gets full customization control.

**Questions to stress-test:**
- Why switch? Why now? What is the actual pain: cost, the platform's limits, speed, or governance?
- Is "save the license cost" the real goal, or a proxy for "we keep hitting the platform's limits"? The answer changes the recommendation.

**Assumption register (to be confirmed or refuted in Step 2):**

| # | Assumption | Why it matters | How to test |
|---|---|---|---|
| A1 | The platform really is Power Apps | *The brief says "such as Microsoft Power Apps." It may be Retool or similar. The analysis should hold for either.* | State it explicitly as an assumption |
| A2 | The $250k is mostly per-user licensing | *Power Apps is licensed per end user or per app, not per builder. The cost driver is probably ops staff (KYC analysts, support agents), not the 60 engineers. Building in-house removes the license fee, not the cost of serving those users.* | Pricing research; back-solve the implied user count |
| A3 | Engineers build the apps today, not ops "citizen developers" | *If ops builds them, moving to code takes self-service away from ops and shifts the work onto engineering: a hidden opportunity cost.* | `OPEN:` unknown; state both scenarios |
| A4 | The $250k covers only the 3 apps | *It may also cover Power Automate, Dataverse capacity, or premium connectors, or come bundled with an M365 agreement, so cancelling may not save the full $250k.* | Pricing research |
| A5 | The cost grows with the 10+ new tools | *Per-user plans may make new apps nearly free at the margin, which weakens the "save as we scale" argument.* | Pricing model research |
| A6 | Building in-house = full control | True for the code. *Control also means owning uptime, security patches, SSO, audit logs, and SOC 2 evidence.* | Steps 2 and 4 |
| A7 | Devin output is production-grade for regulated data | Unproven. It is what the prototype tests. | Step 3b |

*Challenge, bias check: we are Devin, evaluating whether to replace a competitor with Devin, for a Cognition take-home. The pull toward "Build" is structural. Mitigation: steelman Power Apps first, and make the recommendation follow from the evidence rather than precede it.*

*Challenge, false binary: "build vs. buy" hides at least four options worth comparing: (1) keep Power Apps; (2) build everything in-house with Devin; (3) hybrid: keep the platform for simple CRUD apps and build the complex or regulated ones; (4) switch to a cheaper low-code tool (Retool, Appsmith, ToolJet). Devin can play a role in options 2, 3, and arguably 4.*

**Output:** filled-in assumption register + a pain-point hypothesis list.

---

## Step 2: Research

**2a. Power Apps:** what it does, its core capabilities, its pricing model and unit economics, why companies pick it (M365/Entra integration, connectors, citizen developers, governance/DLP, compliance certifications), and its limits (delegation limits on data queries, weak version control and testing, vendor lock-in, performance, UX limits).

**2b. Devin:** capabilities, pricing (ACU model; *verify current numbers, don't quote from memory*), security posture (what access Devin needs, data handling, SOC 2), and limits (it writes code but doesn't host or operate it; humans still review).

**2c. Market context:** a quick look at the alternatives (Retool, Appsmith, a custom React + framework stack) so we're not running a two-horse race. *Time-box this to keep it short.*

**2d. Comparison matrix:** Power Apps vs. Devin-built, scored for (a) this team and (b) the Step 1 needs. Columns: build cost, run cost, maintenance, security/compliance, speed to the first tool and to the 10th, customization, lock-in, who can build.

**2e. Feedback into Step 1:** which assumptions or pain points does the research refute? Which value points did the VP miss (e.g. built-in Entra SSO, audit trails, compliance certifications he'd have to rebuild)? Update the register.

**2f. Deliverable: the core capabilities to replicate.** A ranked list of the Power Apps capabilities that matter most to a fintech team shipping many internal tools. This becomes the prototype scope in Step 3. *Hypothesis to test, not a decision yet: the value is less in any single app and more in the shared foundation that makes the 11th app cheap: auth/RBAC, audit logging, data connectors, forms and tables, approval workflows.*

**Output:** research notes (`docs/research/`), the comparison matrix, the updated register, and the ranked capability list.

---

## Step 3a: Pre-prototype gate

Before the 2-hour clock starts, confirm:
- [ ] Capability list ranked; scope cut to what fits in 2 hours.
- [ ] **Success criteria written down before building** (e.g. "a new tool can be added in under X minutes / Y lines"; "every write is in the audit log"; "role-gated actions"). *This prevents judging the prototype after the fact by whatever it happened to do well.*
- [ ] Stack and hosting chosen (run locally plus a demo-able deployment for the Loom).
- [ ] Mock data only: no real PII, seeded fake KYC and refund records.
- [ ] Clock rules agreed (see the open questions).

## Step 3b: Prototype (2-hour cap)

- Build the scope from 2f with Devin. *Suggestion: build the shared foundation plus 2 of the 3 existing apps on top of it, then time how long a 3rd "new" tool takes. That number is the strongest data point for the Loom.*
- **Running build log** (`docs/BUILD_LOG.md`): timestamps, what Devin did vs. what a human had to do, failures, workarounds, and links to Devin sessions and PRs. *This is the raw material for Steps 4 and 6. Capture it live; it can't be reconstructed afterwards.*
- **Non-negotiable:** a GitHub repo with a working prototype; a README covering what it does and how to run it.

---

## Step 4: Evaluate

- Score the prototype against the 3a success criteria. Is it worth using?
- What friction came up while building or deploying it that would block adoption?
- Answer the brief's four required lenses explicitly: **build cost, maintenance burden, security implications, opportunity cost of engineering time.**
- *Suggestion: a simple 3-year total cost of ownership comparison (license vs. Devin usage + engineer review time + hosting + on-call), with the inputs stated so the VP can swap in his own numbers. Show a sensitivity range, not a single figure.*
- What is replicable with Devin, what isn't, and where the risk lies. (Required in the Loom.)

## Step 4b: Recommend *(suggested addition)*

*Your outline has no explicit recommendation step; it's implied across 4 and 5. "Recommend" is one of the four task phases, so I'd make it a named step with a one-line verdict, the 2-3 reasons behind it, what would change our mind, and next steps for both directions plus Devin's role in each (the Loom requires this).*

---

## Step 5: Loom synthesis

- Deliverable: a **timestamped script, 5:00 max** (*about 650-700 spoken words at a normal pace; budget about 60-90s for the demo*).
- It must cover, in order: (1) the most important aspects of Power Apps; (2) how Devin helps if they build, shown through the prototype; (3) what's replicable, what isn't, and the risk; (4) the build-vs-buy recommendation and why; (5) next steps in either direction and where Devin fits.
- Audience: the client's VP of Engineering.
- *Also needed (outside the script): a recorded Loom (you record it), a dry-run timing check, and the demo environment staged before recording.*

---

## Step 6: Key Decisions one-pager

*Challenge, audience conflict: your outline frames this for "a VP." The brief says it's for **Cognition**, "to understand your thought process, not for the hypothetical customer," and asks for an overview of **the system you designed/built, why that scope, key tradeoffs, and architectural decisions.** Recommendation reasoning belongs mainly in the Loom. Proposed fix: center the one-pager on the system and scope decisions, and spend at most a few lines on process, assumptions, and open questions.*

*Challenge, length: process + assumptions + findings + open areas will not fit on 1 page alongside the architecture. Prioritize ruthlessly.*

*Challenge, voice: "Do not submit AI slop." I'll draft from the build log and decision records, but the final wording should be yours, edited down hard.*

Content: system overview, scope chosen and what was cut (and why), 3-5 key tradeoffs and architecture decisions, assumptions that drove them, and what we'd explore with more time.

---

## Cross-cutting

- *Overall time budget: only the prototype is capped (~2h), but over-investing in Steps 1-2 has the same plausibility problem. Suggest time-boxing research too.*
- *Decision log: every time we pick A over B, add a one-line entry (in `TRACKER.md` or a `DECISIONS.md`). Step 6 then mostly writes itself.*
- Final audit against `PROMPT.md` via `TRACKER.md` before submitting.

---

## Open questions for you

1. **One-pager audience:** agree it's for Cognition (system + scope decisions), not the VP?
2. **2-hour clock:** does it cover only the build + README (research and planning excluded)? Do we log actual elapsed time honestly in the README even if it runs over?
3. **Overall deadline / time budget** for the whole take-home?
4. **Roles:** you record the Loom and own the final one-pager wording; I draft both. Correct?
5. **Hosting:** is a local-run prototype enough, or do you want a live deployed URL for the demo?
6. **Stack preference** (if any), or let Step 2f / 3a decide?
