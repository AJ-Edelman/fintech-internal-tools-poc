# Key decisions

**The question I chose to answer.** The VP asked "can Devin build these tools?" I thought that was the
easy part and the wrong test. What the client
pays $250k for is what sits under the screens: shared data, server-side permissions, approvals, audit,
and someone else running it. So I scoped the prototype to test one thing the decision turns on: once
that layer exists in code, what does the next tool cost, and what does the client now own?

**Why this scope.** I ranked what the platform provides into three tiers and set a rule before choosing:
the prototype must exercise every tier 1 item, stub tier 2 openly, and name tier 3 as not shown. Four
scopes were on the table.

| Option | Why I rejected or chose it |
|---|---|
| One polished tool (KYC queue) | The best demo, but it shows nothing about reuse, and the client's question is about 13 tools |
| Refunds + feature flags | Two tools, but they share no business data, so the shared-model claim would be asserted, not shown |
| A config-driven tool engine | Strongest scaling story on paper; in two hours it becomes a worse rebuild of Power Apps |
| **Refunds + a light KYC review** | The smallest pair with shared customer data and a rule that crosses tools (no refund until KYC is approved) |

The price was depth: KYC has no claim/lock, escalation or documents, and the screens are plain tables
and forms. The third tool, limit
overrides, is one the client does not have. I added it last and timed it alone, because the first two
tools shaped the foundation and so could not fairly test it.

**Architecture tradeoffs.**
- *Foundation first, tools thin.* The per-tool cost is the number that decides build versus buy. The cost is coupling: a foundation change touches every tool.
- *Critical rules in the database, not only the application.* Self-approval, the KYC gate, the limit cap and the append-only audit log are triggers. A rule in one tool's code does not bind the next tool or a script. Triggers are harder to read and change, so only rules whose failure is a control failure went there.
- *Workflow as declared states and guards, not hand-written per tool.* This is what made tool 3 cheap. It will fit unusual processes badly, and I did not test one.
- *SQLite, stubbed login, fake payment services.* I spent the two hours on controls, not infrastructure. That is the largest hole in the evidence: hosting, SSO and real integrations are where a real build's cost sits.

**How I used Devin, and why.** I wrote the spec with numbered acceptance criteria in a planning session
and gave only the spec to a fresh build session, so the instructions an engineer would need are on the
page and not hidden in my context. Fresh sessions with no build context checked each milestone, because
a builder grading its own work is not evidence. That caught two real SSN leaks into the audit log that
the builder's own tests passed. The cost is that my time moved into writing and reviewing specs, which
was more than half of the total.

**Where I was wrong or changed course.**
- My first spec was met in full and was still too thin to stand in for the platform: no integrations, no record-level access, bare lists. That was my spec's failure, and a second spec fixed it.
- Devin challenged an admin-set auto-approve limit as a one-person control. I kept it, but added a hard $750 cap enforced in the database.
- A later review found admin changes that weakened controls with no recorded reason. A third spec closed that.

**What I would not claim from this.** Three synthetic tools show the pattern is feasible and the next
tool is cheap to write. They do not price tools 4 to 13, production operation, or migration, and they
cannot match non-engineers building their own tools.
