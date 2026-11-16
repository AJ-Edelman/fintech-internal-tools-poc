# Video outline (5 minutes, for the VP of Engineering)

| Time | Say | Show |
|---|---|---|
| 0:00–0:30 | Your question had three parts: can Devin build these, do we save the license, do we get control. Short answers: yes for the application, unproven until we see the license breakdown, and partly | Title |
| 0:30–1:15 | What you actually get from Power Apps: shared data, rules and permissions at the server, approvals, audit, connectors, and Microsoft running it. And one pricing fact: Premium is per user, unlimited apps, so 10 more tools do not raise the bill | `EVALUATION.md` claims table |
| 1:15–2:45 | Demo. Agent requests a refund; over the limit goes to an approver; the requester cannot approve their own. KYC decision unblocks a refund in the other tool. SSN is masked; reveal is logged. Approved refund sends one payout message. EU agent cannot see a US customer. Audit trail of all of it | Running app |
| 2:45–3:15 | How Devin built it: written spec, 41 minutes for the first two tools, third tool in minutes on the same foundation, fresh sessions checking the work and catching two real SSN leaks | `BUILD_LOG.md` |
| 3:15–4:00 | What this does not show: SSO and MFA, hosting, backups, encryption, retention, real integrations, non-engineers building tools. After a build, your team owns the application, its security and its evidence, and Devin is a new vendor with source access | Limitations list |
| 4:00–4:40 | Three paths: stay, build selected new tools, replace everything. Recommendation: the middle one, as a pilot of delivery and control, not a license saving. It saves about nothing in licenses while the same staff use the three live apps. Stop conditions are set up front; decide the rest at renewal on measured numbers | Three-path table |
| 4:40–5:00 | Either way, first get the license breakdown. If you stay: trim seats, fix the limits you actually hit; Devin's role is small (custom connectors, tests). If you pilot: one or two new tools on your own stack with a named owner; Devin builds and maintains, your engineers specify, review and own | Next steps |

## Draft script

A draft to rewrite in your own words. About 630 spoken words, which leaves room for clicking during the
demo. Before recording: run `make setup && make seed && make demo`, and keep `EVALUATION.md` open in a
second tab.

**0:00–0:30 · Your question** (title or README on screen)

You asked three things: can we build our internal tools with Devin, do we save the $250k license, and do
we get full control. My short answers: yes for the applications themselves; the saving is unproven until
we see what the $250k actually covers; and control is real, but it comes with ownership. Here is what
that rests on.

**0:30–1:10 · What Power Apps gives you today** (claims table in `EVALUATION.md`)

It helps to be clear about what you would be replacing. Power Apps is not only screens. It is one shared
data model across every app, permissions and business rules enforced on the server, approval workflows,
an audit trail, connectors to other systems, and Microsoft running the platform underneath. One pricing
fact matters a lot: Premium is licensed per user with unlimited apps. So ten more tools for the same
staff add roughly nothing to the bill.

**1:10–2:40 · Demo** (running app)

I had Devin build three tools on one shared foundation, with synthetic data.

- *As `agent1`:* I request a $750 refund. It is over the auto-approve limit, so it waits for a second person. The agent who asked cannot approve it.
- *As `approver1`:* I approve it with a reason. The refund page shows the full history, and one payout message went out to a payments service, which is a fake here.
- *As `agent2`, the EU agent:* a refund for a customer whose KYC is still pending is refused. Opening a US customer returns not found. That is record-level access.
- *As `kyc2`:* the queue shows only EU customers. The SSN is masked in the list; opening the customer shows it, and that view is logged. I approve, and the refund tool now accepts that customer. Two tools, one rule, one data model.
- *As `admin1`:* the audit log has every step. Database rules refuse edits and deletes, though they would not stop someone who controls the database itself.

**2:40–3:10 · How Devin built it** (`BUILD_LOG.md`)

Devin built this from written specs with numbered acceptance criteria, in 94 minutes of build time. The
third tool, one you do not have today, reached a passing run in two minutes because the foundation
already existed. Separate Devin sessions that had not seen the build checked the work, and they found
two real leaks of SSNs into the audit log, which were fixed. More than half of the total time went to
deciding what to build and reviewing it, not to building. That is where the cost of each new tool will sit.

**3:10–3:50 · What this does not show, and the risk** (Limitations in the README)

This is a prototype. It has no single sign-on or MFA, no production hosting, backups or encryption, no
real integrations, and nothing was migrated. Operations staff cannot build or change a tool themselves,
which they can on Power Apps. If you build, your team owns the application, its security and its audit
evidence, and Devin becomes a vendor with access to your source code. Two tools in minutes does not tell
us what tools four to thirteen cost.

**3:50–4:35 · Recommendation** (three-path table)

There are three paths: stay, build selected new tools, or replace everything. I recommend the middle
one, as a pilot of delivery speed and control, not as a saving. While the same staff use your three
existing apps, it avoids about zero license cost. Replacing everything is the only path that could save
real money, and nobody has the numbers to judge it yet. The pilot is the cheapest way to get them.

**4:35–5:00 · Next steps** (Next steps section)

Either way, start with the license breakdown and renewal date. If you stay, trim unused seats and fix
the limits you actually hit; Devin's role there is small. If you pilot, pick one or two new tools the
platform handles badly, build them on your own stack with a named owning team, and measure review hours
and upkeep for a quarter. Stop if no one will own it, or if the second tool is not clearly cheaper than
the first. Then decide at renewal.
