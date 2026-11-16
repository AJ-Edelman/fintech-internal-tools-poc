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
