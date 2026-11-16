# Video outline (5 minutes, for the VP of Engineering)

| Time | Say | Show |
|---|---|---|
| 0:00–0:30 | Your question had three parts: can Devin build these, do we save the license, do we get control. Short answers: yes, not as much as you think, and partly | Title |
| 0:30–1:15 | What you actually get from Power Apps: shared data, rules and permissions at the server, approvals, audit, connectors, and Microsoft running it. And one pricing fact: Premium is per user, unlimited apps, so 10 more tools do not raise the bill | `EVALUATION.md` claims table |
| 1:15–2:45 | Demo. Agent requests a refund; over the limit goes to an approver; the requester cannot approve their own. KYC decision unblocks a refund in the other tool. SSN is masked; reveal is logged. Approved refund sends one payout message. EU agent cannot see a US customer. Audit trail of all of it | Running app |
| 2:45–3:15 | How Devin built it: written spec, 41 minutes for the first two tools, third tool in minutes on the same foundation, fresh sessions checking the work and catching two real SSN leaks | `BUILD_LOG.md` |
| 3:15–4:00 | What this does not show: SSO and MFA, hosting, backups, encryption, retention, real integrations, non-engineers building tools. After a build, your team owns all of it | Limitations list |
| 4:00–4:40 | Recommendation: keep the platform and the three live tools; build the next one or two new tools in code; decide the rest at renewal on measured numbers | Recommendation |
| 4:40–5:00 | Next steps: get the license breakdown; pick the pilot tools; name an owning team. Devin builds and maintains, your engineers specify, review and own | Next steps |
