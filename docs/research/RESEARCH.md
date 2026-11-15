# Step 2: Research (bounded, sourced)

Scope: only the capabilities relevant to this client. No market survey. All sources accessed **2026-11-15**. Prices are US list prices; actual contracts vary [S1][S3].

## 2a. The platform beneath the screens

| Capability | What provides it | License dependency | Fintech relevance |
|---|---|---|---|
| App UI (canvas / model-driven) | Power Apps | Premium $20/user/mo, unlimited apps [S1]; per-app $5/user/app/mo [S2] | Fast CRUD screens for ops staff |
| Data model + persistence | Dataverse (tables, relationships, business logic) [S1] | 250 MB DB + 2 GB file per Premium user, tenant-pooled; extra capacity sold per GB [S1] | System of record for queue/case data |
| Row-level permissions | Dataverse security roles + business units; privileges are cumulative [S5] | Requires a Dataverse environment [S5] | Who can see or act on which records |
| Column-level permissions / masking | Dataverse column-level security [S6] | Dataverse; masking rules are a Managed Environments feature [S4] | PII masking (SSN, bank details) |
| Audit trail | Dataverse auditing (record changes; not reads or exports) [S10] | Consumes Dataverse log capacity [S10] | Who changed what, and when |
| Approvals / workflow | Power Automate approvals connector (all/first/sequential) [S11] | Standard connector; flows must run "in the context of the app," otherwise a separate Power Automate license is needed (Premium $15/user/mo) [S2] | Maker-checker, escalations |
| Integrations | Prebuilt, custom, and on-prem connectors [S1] | Premium connectors need a Premium license [S1][S3] | Internal APIs, payment processor, KYC vendor |
| Governance / DLP | Data policies classify connectors to prevent data exfiltration [S8] | Core; extended by Managed Environments [S4] | Data-loss controls |
| Environment governance | Managed Environments (sharing limits, IP firewall, CMK, lockbox, app allow-lists) [S4] | Included with standalone licenses [S4] | Production control |
| ALM / deployment | Solutions + Pipelines in Power Platform [S9] | Managed Environments [S4][S9] | Change control into prod |
| Runtime / ops | Microsoft-operated: TLS, encryption at rest (TDE), geo residency [S12] | Included | Platform layer is Microsoft's to operate |

**Known limits that matter here**
- **Delegation:** non-delegable queries process only the first N records (default 500, max 10,000) and can return **incorrect results without failing** [S7]. This is a real risk for queues that grow past thousands of records.
- **Auditing excludes reads and exports** [S10]. PII *access* logging needs extra tooling.
- **Licensing churn:** per-app licenses are no longer sold to new customers in some channels since 2026-01-02 [S3]; unmanaged developer environments are deprecated [S2][S4].

## 2b. Unit economics (what the sources support)
- At list price, $250k/yr ≈ 1,040 Premium users, or ≈ 4,170 per-app user-app licenses [S1][S2]. Both look large for a company with ~60 engineers, so the $250k likely includes other services (A4). **We take $250k as the total but treat the avoidable share as an open input.**
- The marginal license cost of a new tool is ~$0 for users who already have Premium [S1]. It is non-zero only for new users, new capacity, or standalone flows [S2].

## 2c. Devin (bounded)
- **What it is:** an autonomous coding agent that writes, tests, and opens PRs against the client's repos. It is **not a runtime, database, or IdP**; the built apps run on the client's own infrastructure. *(Product fact, consistent with [S13][S14].)*
- **Pricing:** self-serve Teams plan $80/mo minimum, $40/mo per full seat, with usage beyond quota billed in dollars; Enterprise is billed in ACUs at contract rates [S13]. The usage cost of a given build is measured, not assumed. We'll record it from the prototype build.
- **Security posture:** SOC 2 Type II since 2024-09; encryption in transit and at rest; repo access scoped through the GitHub App; Enterprise data isn't used for training without consent; paid plans can opt out [S14].
- **Access footprint to evaluate:** repo access plus whatever credentials sessions get. Prototype rule: **synthetic data only, no production credentials.**

## 2d. Feedback into Step 1
- A2 confirmed; A5 **refuted** for per-user Premium; A4 flagged (the implied user count looks implausible). See [`../ASSUMPTIONS.md`](../ASSUMPTIONS.md).
- **Reframe:** the cost argument mainly applies to *retiring the existing spend* (path c), not to *building new tools* (path b). Path b has to win on fit, control, and speed.
- Value the VP may miss: identity, row/column security, auditing, DLP, a Microsoft-operated runtime. All of these are rebuild-and-evidence work if they build.

## 2d-bis. Shared context and coupling (resolves A10)
- **Shared context is a core value, not a side effect.** Dataverse gives every app the same tables (standard tables plus custom ones), relationships, and metadata [S18], and the same security roles and audit [S5][S10]. A KYC decision is immediately visible to the refunds app without an integration.
- **Its cost is documented coupling:** a single shared unmanaged layer [S15][S16], "top wins" component layering [S15], cross-solution table dependencies that break upgrades and deletes [S17].
- **Implication for build:** any credible build has to provide shared context as well: one data model with shared entities (e.g. `customer`), one identity and role model, one audit log, one approval engine. A set of standalone apps would lose the platform's main value. The coupling comes along with it, so the prototype must measure it, not hide it.

## 2e. Core Power Apps capabilities for this client (consolidated)

This consolidates 2a (what exists) and 2d-bis (shared context) into one ranked list. **Tier 1** = critical: a credible build must provide it, or the client loses something it has today. **Tier 2** = important but can be phased or stubbed. **Tier 3** = real but outside a prototype's reach.

Replicability: **E** = easy with Devin, **M** = needs deliberate engineering + review, **H** = platform-native, costly to replicate or evidence.

| Tier | Capability | Platform source | Why it matters here | Replicability |
|---|---|---|---|---|
| 1 | **Shared data model / context across apps** | Dataverse tables, relationships [S18] | KYC status visible to refunds without integration; 13 tools on one model | M (coupling comes with it: A10) |
| 1 | **Data-layer business rules** (validation enforced at the server, for every app that writes the table) | Dataverse business rules "apply to all the table forms and at the server level" for canvas and model-driven apps [S20] | With 13 tools writing shared tables, invariants (e.g. refund ≤ original charge) can't live in each app's UI | M |
| 1 | **Server-enforced permissions** (role, record, column/PII) | Dataverse roles, business units [S5], column security [S6] | KYC/refund data; separation of duties | M |
| 1 | **Workflow: stage-gated process + approvals** (maker-checker, thresholds, required data before advancing) | Power Automate approvals [S11]; business process flows with stage-gating [S21] | Money movement, KYC decisions | M |
| 1 | **Audit trail of every state change** | Dataverse auditing [S10] | Regulators, internal audit | M (reads/exports: H on both sides) |
| 1 | **Reusable foundation: tool N+1 is cheap** | Implicit: every app gets the above for free | 10+ tools planned | M (makes or breaks "build") |
| 2 | Persistent data + forms/tables UI | Canvas / model-driven apps [S1] | Every tool needs it | E |
| 2 | SSO + group-based access via the corporate IdP | Environments are bound to an Entra tenant [S22]; roles assignable to Entra security-group teams [S5] | Joiner/mover/leaver control | M (prototype stubs it) |
| 2 | Change control / ALM + dev/test/prod separation | Solutions + Pipelines [S9]; environments separate test/prod, each bound to a geography [S22] | Regulated changes | E with git/CI (a build strength) |
| 2 | Integrations to internal/vendor APIs | Connectors [S1] | Payments, KYC vendor | M per integration |
| 2 | **Low-code authoring by non-engineers** | Maker experience; **Copilot generates apps from natural language** [S19] | Decides *who* builds and maintains (A3). If ops builds today, code moves that work to engineers | H: Devin speeds engineers up but doesn't remove engineering review |
| 3 | Governance at scale (DLP, environments, app inventory) | Data policies [S8], Managed Environments [S4] | Many tools, many owners | H |
| 2 | Document attachments (e.g. KYC ID scans) | Dataverse File/Image column types [S25] | KYC evidence | E–M (storage + access control) |
| 3 | Operated runtime (patching, residency, encryption, backup/DR) | Microsoft-operated [S12]; automatic backups, 7 days default, up to 28 for production managed environments [S23] | Compliance evidence | H (moves to client: A8) |

**Gaps in earlier drafts, now added:** shared data context (2d-bis), low-code authoring, and from the second pass (below) data-layer business rules and stage-gating.

### Second pass (2026-11-15): what else Power Apps provides, and the verdict
| Found | Verdict |
|---|---|
| Server-side business rules on tables, shared by all apps [S20] | **Added to Tier 1.** The only new must-replicate item. Without it, each tool re-implements (and drifts on) the same invariants |
| Business process flows: stages, required steps, stage-gating [S21] | Folded into the Tier 1 workflow row (a state machine with guards) |
| Copilot / "Plans" build apps from natural language [S19] | **Weakens the Devin-speed argument:** the platform also has AI-assisted building. The difference is the output (platform artifacts vs. code the client owns), not AI vs. no AI |
| Environments: tenant-bound, geo-bound, test/prod separation [S22] | Tier 2 (folded into ALM) |
| Automatic backups, 7–28 day retention; restore only into sandbox [S23] | Tier 3 (operated runtime) |
| File/image columns [S25] | Tier 2 (KYC documents) |
| Mobile and offline model-driven apps [S24] | Not needed: back-office ops tools |
| Dynamics 365 shares the same Dataverse [S19] | If the client uses Dynamics, the $250k may be bundled (A4) and retiring the platform is harder |
| Real-time workflows, actions, plug-ins, Azure functions [S19][S20] | Pro-dev extensibility exists on the platform too; it partly answers the "customization control" pain (H2) |

**Rule for scope selection:** the prototype must exercise **all Tier 1 items**, stub Tier 2 items explicitly, and name Tier 3 items as not established.

## 2f. Prototype scope candidates (for decision, not yet chosen)

All candidates share the **same reusable foundation** to address scale: server-side RBAC middleware, an append-only audit log, a typed data layer, and a state-machine/approval module. A "how to add tool N" path shows reuse instead of asserting it.

Tier 1 items: **T1a** shared data model, **T1b** data-layer rules, **T1c** server-enforced permissions, **T1d** workflow, **T1e** audit, **T1f** reusable foundation.

| Option | Workflow | Tier 1 covered | Scaling evidence | Risk in 2h |
|---|---|---|---|---|
| **A** | Refund maker-checker + feature-flag change requests on the same foundation | b, c, d, e, f (**not a**: the tools share no business data) | Tool #2 built from the template, timed, new lines counted | Medium |
| **A2** | Refund maker-checker + light KYC review (review a customer, record a decision with a reason; no claim/lock, escalation, or documents) on a shared `customer` table; cross-tool rule (no refund while KYC pending/failed) enforced at the server; **server-side PII masking by role** on 2–3 columns, with unmasked reads written to the audit log; audit log append-only **enforced in the database** and detailed enough to reconstruct a refund; role assignments listable for access review; CI runs backend tests on every push; tool #2 forces one shared-model change and tool #1's tests must still pass. Small default seed for the demo; separate `--scale` seed (50k records) for the paging check only | **a–f** (incl. column-level in c) | Tool #2 timed, new lines counted, coupling measured | Medium-high (managed by trimming KYC breadth, not Tier 1) |
| **B** | KYC review queue only (claim/lock, decision, escalation, PII masking) | a (one tool), b, c, d, e (**not f**) | Reuse argued, not shown | Medium |
| **C** | Config-driven generic tool engine | a, f on paper | Strong on paper | **High**: drifts toward rebuilding the platform |

*Pending your decision.* Against the rule above, only A2 exercises all of Tier 1.

**What any option will not establish:** real IdP/SSO integration, production hosting and on-call, scale or performance, SOC 2 evidence, migration of existing Dataverse data, or the cost of tools 3–13.

## 2g. Cross-check: what a fintech's internal tools must satisfy (beyond Microsoft's feature list)

Sections 2a–2e list what Power Apps *provides*. This pass asks what a fintech's internal tools are *required* to do, from the rules most likely to apply (applicability is assumption A11), plus one survey of engineering teams.

| Requirement | Source | Already in Tier 1/2? | Change to the prototype |
|---|---|---|---|
| Least-privilege access; periodic access review; prompt removal after departures | FTC Safeguards 314.4(c)(1) [S26]; NYDFS 500.7 (review at least annually) [S28] | T1c permissions; Tier 2 SSO | **Add:** role assignments stored as data and listable for an access review |
| Separation of duties | NIST SP 800-53 AC-5 [S30] | T1d maker-checker | None (no self-approval already planned). Admins must not be able to edit the audit log (AC-5 guidance) |
| Log user activity; detect tampering | FTC 314.4(c)(8) [S26]; NIST AU-9 protect audit records from modification/deletion [S30] | T1e audit | **Add:** append-only enforced **in the database** (update/delete on audit rows fails), plus a test. Unmasked-PII reads are already logged |
| Reconstruct material financial transactions; keep records 5 years | NYDFS 500.6 [S29]; BSA records 5 years [S27] | T1e audit | **Add:** audit entries carry who, what, before/after values, reason, time, so a refund's history can be rebuilt from the log alone. Retention itself is **not established** |
| Secure development practices for in-house apps | FTC 314.4(c)(4) [S26] | Not listed before | **CI becomes required:** backend tests run automatically on every push. Applies specifically to *building* |
| Change-management procedures | FTC 314.4(c)(7) [S26] | Tier 2 ALM | Covered by git + CI + PR review |
| MFA for anyone accessing customer data | FTC 314.4(c)(5) [S26] | Tier 2 SSO | Not established (IdP's job; prototype stubs login) |
| Encryption in transit and at rest | FTC 314.4(c)(3) [S26] | Tier 3 runtime | Not established (hosting) |
| Dispose of customer data within 2 years of last use unless retention is required | FTC 314.4(c)(6) [S26] | Not listed before | Not established. Note the tension with 5-year retention: data lifecycle is a capability every built tool needs |

**Engineering-team view (vendor survey, treat with caution):** Retool's 2022 survey (>2,000 respondents, mostly developers) found ~33% of respondents' time went to building internal tools, most often on Postgres and internal APIs, and flagged a "worryingly lax approach" to security in internal tools [S31]. That supports the shared, secure foundation as the thing to test, not single-app speed.

**Net result:** no new Tier 1 capability, but three Tier 1 items get stricter (tamper-resistant audit, reconstructable audit, reviewable role assignments) and CI moves from stretch to required.

## Sources (accessed 2026-11-15)
- [S1] Microsoft, *Power Apps licensing and pricing*: https://www.microsoft.com/en-us/power-platform/products/power-apps/pricing
- [S2] Microsoft Learn, *Power Platform licensing FAQs*: https://learn.microsoft.com/en-us/power-platform/admin/powerapps-flow-licensing-faq
- [S3] Microsoft Learn, *Licensing overview for Microsoft Power Platform*: https://learn.microsoft.com/en-us/power-platform/admin/pricing-billing-skus
- [S4] Microsoft Learn, *Managed environments overview*: https://learn.microsoft.com/en-us/power-platform/admin/managed-environment-overview
- [S5] Microsoft Learn, *Ownership-based security in Dataverse*: https://learn.microsoft.com/en-us/power-platform/admin/wp-security-cds
- [S6] Microsoft Learn, *Column-level security*: https://learn.microsoft.com/en-us/power-platform/admin/field-level-security
- [S7] Microsoft Learn, *Understand delegation in a canvas app*: https://learn.microsoft.com/en-us/power-apps/maker/canvas-apps/delegation-overview
- [S8] Microsoft Learn, *Data policies*: https://learn.microsoft.com/en-us/power-platform/admin/wp-data-loss-prevention
- [S9] Microsoft Learn, *Overview of pipelines in Power Platform*: https://learn.microsoft.com/en-us/power-platform/alm/pipelines
- [S10] Microsoft Learn, *Manage Dataverse auditing*: https://learn.microsoft.com/en-us/power-platform/admin/manage-dataverse-auditing
- [S11] Microsoft Learn, *Get started with Power Automate approvals*: https://learn.microsoft.com/en-us/power-automate/get-started-approvals
- [S12] Microsoft Learn, *Compliance and data privacy (Power Platform)*: https://learn.microsoft.com/en-us/power-platform/admin/wp-compliance-data-privacy
- [S13] Cognition, *Devin self-serve plans* / *Billing*: https://docs.devin.ai/admin/billing/self-serve, https://docs.devin.ai/admin/billing
- [S14] Cognition, *Security at Cognition*: https://docs.devin.ai/admin/security
- [S15] Microsoft Learn, *Solution layers and merge behavior*: https://learn.microsoft.com/en-us/power-platform/alm/solution-layers-alm
- [S16] Microsoft Learn, *Solution concepts*: https://learn.microsoft.com/en-us/power-platform/alm/solution-concepts-alm
- [S17] Microsoft Learn, *Organize your solutions*: https://learn.microsoft.com/en-us/power-platform/alm/organize-solutions
- [S18] Microsoft Learn, *What is Microsoft Dataverse?*: https://learn.microsoft.com/en-us/power-apps/maker/data-platform/data-platform-intro
- [S19] Microsoft Learn, *What is Power Apps?*: https://learn.microsoft.com/en-us/power-apps/powerapps-overview
- [S20] Microsoft Learn, *Apply business logic in Dataverse*: https://learn.microsoft.com/en-us/power-apps/maker/data-platform/processes
- [S21] Microsoft Learn, *Business process flows overview*: https://learn.microsoft.com/en-us/power-automate/business-process-flows-overview
- [S22] Microsoft Learn, *Power Platform environments overview*: https://learn.microsoft.com/en-us/power-platform/admin/environments-overview
- [S23] Microsoft Learn, *Back up and restore environments*: https://learn.microsoft.com/en-us/power-platform/admin/backup-restore-environments
- [S24] Microsoft Learn, *Overview of building a model-driven app*: https://learn.microsoft.com/en-us/power-apps/maker/model-driven-apps/model-driven-app-overview
- [S25] Microsoft Learn, *Column data types in Dataverse*: https://learn.microsoft.com/en-us/power-apps/maker/data-platform/types-of-fields
- [S26] eCFR, *16 CFR 314.4 (FTC Safeguards Rule), Elements*: https://www.ecfr.gov/current/title-16/chapter-I/subchapter-C/part-314/section-314.4
- [S27] eCFR, *31 CFR 1010.430, Nature of records and retention period*: https://www.ecfr.gov/current/title-31/subtitle-B/chapter-X/part-1010/subpart-D/section-1010.430
- [S28] LII, *23 NYCRR 500.7, Access privileges and management*: https://www.law.cornell.edu/regulations/new-york/23-NYCRR-500.7
- [S29] NYDFS, *23 NYCRR 500 (incl. 500.6 Audit Trail)*: https://www.dfs.ny.gov/system/files/documents/2023/03/23NYCRR500_0.pdf
- [S30] NIST, *SP 800-53 Rev. 5, controls AC-5 and AU-9*: https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final (control text via https://csf.tools/reference/nist-sp-800-53/r5/ac/ac-5/ and /au/au-9/)
- [S31] Retool, *The state of internal tools 2022* (vendor survey): https://retool.com/blog/the-state-of-internal-tools-2022
