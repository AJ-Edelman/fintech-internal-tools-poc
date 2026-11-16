# Key decisions

**What was built.** Three internal tools on one shared foundation: refund requests with maker-checker
approval, KYC review, and account limit overrides. The foundation supplies what Power Apps gives every
app: one customer model, permissions by role, region and column, a declarative approval workflow, an
append-only audit log, outbound connections with retry, and one list component with search, sort and
paging. FastAPI, SQLite, server-rendered pages, pytest, GitHub Actions. Synthetic data only.

**Why this scope.** The client's question is about 13 tools, so one polished tool would answer the wrong
question. I ranked what the platform provides into three tiers and required the prototype to exercise
every tier 1 item, stub tier 2 openly, and name tier 3 as not established. Refunds plus KYC was the
smallest pair that shares business data and needs a rule across tools (no refund while KYC is not
approved). The feature-flag panel shares no data with either, so it was left out. The third tool is one
the client does not have today, built last and timed alone, to test whether the foundation carries a new
tool or only the ones it was designed around.

**Architecture decisions and their tradeoffs**

| Decision | Why | Cost |
|---|---|---|
| The foundation is the product, tools are thin | The per-tool cost is what decides build versus buy | The foundation couples every tool; a change to it touches all of them, as on the platform |
| Controls enforced on the server, the critical ones in the database | A rule in one tool's screen does not bind the next tool or a script | Triggers are harder to read and change than application code |
| Workflow declared as data (states, transitions, guards) | A new tool declares its process and reuses approval, audit and scope checks | Less flexible than hand-written logic for unusual flows |
| SQLite and a stubbed login | Runs anywhere in one command; keeps the two hours on the controls | Says nothing about hosting, SSO, MFA or concurrency |
| Fake payments and ledger services | Shows delivery exactly once, failure and retry without credentials | Real integrations cost is unmeasured |
| Spec with numbered acceptance criteria before any code; fresh Devin sessions with no build context checking each milestone | The builder should not grade its own work. The checks found two real SSN leaks into the audit log | More elapsed time than building straight through; the human cost moves into writing and reviewing specs |
| Independent pieces built in parallel after contracts were fixed | Tests how Devin would be used across many tools | Elapsed time and total work time diverge; both are logged |

**Decisions I reversed or was overruled on.** I argued against an admin-set auto-approve limit as a
single-person control; it was kept with a hard cap of $750. The first build met its spec and was still
too thin to stand in for the platform (no integrations, no record-level access, bare lists), because the
spec asked for too little. A second spec closed that. A review then found admin changes that weakened
controls without a recorded reason, and a third spec fixed those.

**What the design does not establish.** Real SSO or MFA; production hosting, backups, encryption,
retention; real integrations; document attachments; non-engineers building tools, which is the
platform's one capability code cannot match; migration of existing data; and the cost of tools 4 to 13.
The timings are two data points on synthetic tools. They show a new tool is cheap to write on an
existing foundation, not that owning thirteen is cheaper than the license.
