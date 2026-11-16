# Key decisions

**How I approached the question.** The VP asked whether the team could build its tools with Devin, save
the $250k and gain control. I started neutral, with no default to "stay" or "build", and split the ask
into two questions with different economics: replacing three live apps (migration, parallel running,
retraining) and building ten new ones (greenfield). That gave three paths: stay, build selected new
tools, replace everything. I also compared like with like. Power Apps is screens plus a data platform,
workflow, identity, governance and a runtime Microsoft operates. Devin writes code; it does not host or
operate anything. So "can Devin build a refunds screen" was the easy and wrong test. The test that
matters is what the next tool costs once that layer exists in code, and what the client then owns.

**Assumptions I worked from, and what they did to the design.**
- *The $250k is real, but the avoidable share is unknown.* Research showed Premium is per user with unlimited apps, which refuted my starting assumption that ten more tools raise the bill. The prototype therefore could not prove a saving, so I designed it to produce cost inputs (time, review effort, reuse), not a savings figure.
- *Internal-tool users are operations staff, not engineers,* and they may build their own apps today. Code moves that work to engineers. I could not test this and say so.
- *The client already has cloud, sign-in and CI.* If not, the build case is much weaker.

**What "scale" means here.** "Ten more tools" hides five questions: more tools, more users, delivery
speed, data volume, and governance across many apps. Two hours could speak to the first and part of the
fourth. So I built tools on a shared foundation and measured the marginal one, and added a 50,000-record
paging check. More users and governance are named as not shown.

**Why this scope.** I ranked what the platform provides into three tiers and set a rule before choosing:
exercise every tier 1 item, stub tier 2 openly, name tier 3 as not shown.

| Option | Why rejected or chosen |
|---|---|
| One polished tool (KYC queue) | Best demo; shows nothing about reuse |
| Refunds + feature flags | The tools share no business data, so the shared-model claim would be asserted |
| A config-driven tool engine | Best scaling story on paper; in two hours, a worse rebuild of Power Apps |
| **Refunds + a light KYC review** | Smallest pair with shared customer data and a rule that crosses tools |

The price was depth: no KYC claim/lock, escalation or documents, and plain screens. The third tool,
limit overrides, is one the client does not have. I timed it alone, because the first two tools shaped
the foundation and could not fairly test it.

**Architecture tradeoffs.**
- *Foundation first, tools thin.* Per-tool cost decides build versus buy. The cost is coupling: a foundation change touches every tool.
- *Critical rules as database triggers* (self-approval, KYC gate, limit cap, append-only audit), so they bind every tool and script. Triggers are harder to change, so only control failures went there.
- *Workflow declared as states and guards.* This made tool 3 cheap; it will fit unusual processes badly, which I did not test.
- *SQLite, stubbed login, fake payment services.* Two hours went to controls, not infrastructure. That is the largest hole: hosting, SSO and real integrations are where a real build's cost sits.
- *Spec first, built in a fresh Devin session, checked by other fresh sessions.* A builder grading itself is not evidence; the checkers caught two SSN leaks the builder's tests passed.

**Where I was wrong or changed course.** My first spec was met in full and was still too thin to stand in
for the platform, which was the spec's failure. Devin challenged the admin-set auto-approve limit as a
one-person control; I kept it with a hard $750 cap. A review found admin changes with no recorded reason.

**What I would not claim.** Three synthetic tools show feasibility and a cheap next tool. They do not
price tools 4 to 13, production operation or migration.
