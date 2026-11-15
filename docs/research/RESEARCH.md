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
| 1 | **Server-enforced permissions** (role, record, column/PII) | Dataverse roles, business units [S5], column security [S6] | KYC/refund data; separation of duties | M |
| 1 | **Approval workflow** (maker-checker, thresholds) | Power Automate approvals [S11] | Money movement, KYC decisions | M |
| 1 | **Audit trail of every state change** | Dataverse auditing [S10] | Regulators, internal audit | M (reads/exports: H on both sides) |
| 1 | **Reusable foundation: tool N+1 is cheap** | Implicit: every app gets the above for free | 10+ tools planned | M (makes or breaks "build") |
| 2 | Persistent data + forms/tables UI | Canvas / model-driven apps [S1] | Every tool needs it | E |
| 2 | SSO via the corporate IdP | Entra ID (implicit in licensing [S3]) | Joiner/mover/leaver control | M (prototype stubs it) |
| 2 | Change control / ALM into prod | Solutions + Pipelines [S9] | Regulated changes | E with git/CI (a build strength) |
| 2 | Integrations to internal/vendor APIs | Connectors [S1] | Payments, KYC vendor | M per integration |
| 2 | **Low-code authoring by non-engineers** | Maker experience [S1] | Decides *who* builds and maintains (A3). If ops builds today, code moves that work to engineers | H: Devin speeds engineers up but doesn't remove engineering review |
| 3 | Governance at scale (DLP, environments, app inventory) | Data policies [S8], Managed Environments [S4] | Many tools, many owners | H |
| 3 | Operated runtime (patching, residency, encryption, DR) | Microsoft-operated [S12] | Compliance evidence | H (moves to client: A8) |

**Gaps in earlier drafts, now added:** shared data context (found in 2d-bis) and low-code authoring (the economic counterweight to Devin's throughput argument).

**Rule for scope selection:** the prototype must exercise **all Tier 1 items**, stub Tier 2 items explicitly, and name Tier 3 items as not established.

## 2f. Prototype scope candidates (for decision, not yet chosen)

All candidates share the **same reusable foundation** to address scale: server-side RBAC middleware, an append-only audit log, a typed data layer, and a state-machine/approval module. A "how to add tool N" path shows reuse instead of asserting it.

| Option | Workflow | Covers (2e) | Scaling evidence | Risk in 2h |
|---|---|---|---|---|
| **A** | Refund maker-checker (threshold → second approver, no self-approval, audit) **+ a second tool on the same foundation** (feature-flag change requests with approval) | 1, 2, 3, 4, 5, 7 | Tool #2 built from the template, timed, measured by new lines of code | Medium |
| **B** | KYC review queue (claim/lock, decision with reason, escalation, PII masking by role) | 1, 2, 3, 4, (column security) | One tool only; reuse is argued, not shown | Medium |
| **C** | Config-driven generic tool engine (define a tool in YAML) | 4, 5 | Strong on paper | **High**; it drifts toward "rebuilding the platform," which we ruled out |

*Recommendation: A.* It directly tests the riskiest "build" claim (#5: is tool N+1 cheap?) with a fintech control (maker-checker) and a denied path that can be checked at the API. Tool #2 reuses the existing feature-flag admin domain. *B is the fallback if you'd rather show column-level PII masking.*

**What any option will not establish:** real IdP/SSO integration, production hosting and on-call, scale or performance, SOC 2 evidence, migration of existing Dataverse data, or the cost of tools 3–13.

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
