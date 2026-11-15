# Deliverables & Constraints Tracker

Running checklist for auditing final output against [`PROMPT.md`](./PROMPT.md) (the read-only brief).
Mark items `[x]` as they are completed and add a short note/link as evidence.

## Context

- Client: Series C fintech, ~60 engineers
- Current spend: $250k/yr on an internal tool platform (e.g. Microsoft Power Apps)
- Existing apps: KYC review queue, refunds dashboard, feature-flag admin panel
- Pipeline: 10+ more internal tools planned
- Ask (VP Eng): can Devin build these, save the license cost, and give full customization control?

## Constraints

- [ ] Prototype time-boxed to ~2 hours (hard cap: do not exceed 2h). Started: _TBD_ / Finished: _TBD_
- [ ] Prototype must be built with Devin (Devin Cloud)
- [ ] Prototype focuses on Power Apps capabilities that matter most to a fintech team building many tools
- [ ] Loom video is 5 minutes max
- [ ] Loom audience is the client's VP of Engineering
- [ ] Key Decisions one-pager is 1 page max
- [ ] One-pager audience is Cognition (thought process), not the client
- [ ] One-pager is not AI slop: specific, concrete, in our own voice
- [ ] Recommendation is a clear build-vs-buy call; reasoning quality matters more than which side

## Task Phases

- [ ] **Research**: what Power Apps does, its core capabilities, and where its value lies for this team
- [ ] **Prototype**: working Devin-built replica of core Power Apps functionality
- [ ] **Evaluate**: honest Devin vs Power Apps comparison covering:
  - [ ] Build cost
  - [ ] Maintenance burden
  - [ ] Security implications
  - [ ] Opportunity cost of engineering time
- [ ] **Recommend**: clear build-vs-buy recommendation with reasoning

## Deliverables

### 1. Working Prototype (GitHub repo)

- [x] Repo exists: https://github.com/AJ-Edelman/fintech-internal-tools-poc
- [ ] Contains what was built with Devin
- [ ] README explains what it does
- [ ] README explains how to run it

### 2. Loom Video (5 min max, for VP Eng)

- [ ] Most important aspects of Microsoft Power Apps
- [ ] How Devin helps if they build, illustrated with the prototype
- [ ] Honest assessment: what's replicable with Devin
- [ ] Honest assessment: what's not replicable
- [ ] Honest assessment: where the risk lies
- [ ] Build vs Buy recommendation and reasoning
- [ ] Next steps if they proceed (either direction) and where Devin fits, if anywhere
- [ ] Runtime checked at 5:00 or under

### 3. Key Decisions One-Pager (1 page max, for Cognition)

- [ ] Overview of the system designed/built
- [ ] Why this scope was chosen
- [ ] Key tradeoffs
- [ ] Architectural decisions
- [ ] Fits on one page

## Final Audit

- [ ] Re-read `PROMPT.md` line by line and confirm every item above is addressed
