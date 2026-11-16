# Kickoff prompt for the build session

Paste the text below as the first message of the fresh build session. It counts as instruction input alongside `BUILD_SPEC.md`.

---

Implement `docs/BUILD_SPEC.md` on a new branch and open a PR. Follow it strictly, including its time limit. Work this way:

1. **Order:** build `app/foundation/` and migration 001 first, then tool 1. Tag `tool1-done` only when its criteria pass. Don't start tool 2 before that tag.
2. **Parallel work:** once the foundation is stable, you may give background subagents self-contained pieces (the scale seed and its paging test, CI and the Makefile, the README). Never let two workers edit the same file. Log what you delegated and any rework.
3. **Independent check:** at each tag, have a fresh subagent with no build context run `make test` and `make verify` and try to break the criteria due at that milestone. Fix only failed criteria; log anything else it finds. Never weaken a test. Report exact command output.
