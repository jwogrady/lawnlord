You are Claude Code operating inside the jwogrady/lawnlord repo.

Important distinction:

- Spark is the workflow reference (the process rails).
- Lawnlord is the target repo (what you inspect and modify).

Do not work inside jwogrady/spark unless explicitly asked.
Use Spark's lifecycle as the process rails, but inspect and modify jwogrady/lawnlord.

Workflow:

Ideate → Plan → Codify → Validate → Ship

Spark commands (Spark 0.3.1 — verified installed):

- /spark:ideate    — frame a fuzzy problem
- /spark:plan      — turn a framed problem into scoped issues + milestone
- /spark:codify    — implement one scoped issue on a feature branch
- /spark:validate  — harden ONE branch/diff: runs /code-review + /security-review + verify, then fixes findings
- /spark:ship      — conventional commit, push, open one focused PR

(Note: /spark:validate is the Stage-4 skill in 0.3.1. There is no /spark:fix-issue
in 0.3.1 — it was renamed to validate. /spark:review is a whole-PROJECT audit, not a
single-diff gate; use it only for repo-wide audits. Native /code-review, /security-review,
and the verify skill are also available directly.)

Core rule:

GitHub Issues in jwogrady/lawnlord are the source-of-truth backlog.
Do not invent new implementation work until existing Lawnlord issues have been inspected.

Author:

jwogrady

Attribution rule (stated once — applies to every commit, PR, and credit field):

Never credit Claude, Anthropic, an AI assistant, or any agent as an author. Use jwogrady.

Repo safety rules:

- Work in jwogrady/lawnlord (expected at /home/john/workspace/lawnlord).
- Never commit directly to master or main.
- Never force-push.
- Never bypass Spark guardrails.
- Use one feature branch per concern. Prefer one issue per branch.
- Keep commits conventional. Keep commit subjects <= 72 chars. No AI attribution trailers.
- Prefer small, reversible diffs.
- There is an untracked CLAUDE.md in the working tree at start. Leave it untracked —
  do NOT add it to your feature work unless an issue is explicitly about it.
- Validate before shipping.
- If uncertainty exists, inspect repo files and GitHub Issues instead of guessing.

Autonomy for this run:

Run the full lifecycle in one go — Ideate (if needed) → Plan → Codify → Validate → Ship —
ending at an OPEN PULL REQUEST. Rely on the repo-safety rails and the validation contract
below as guardrails. Do not stop for human approval mid-loop, but DO stop and ask if a
safety rule would otherwise be violated, if the selected issue is genuinely blocked, or if
acceptance criteria cannot be met without inventing legal/factual content.

Ready-for-Codify-or-stop brake:

This run only auto-codes an issue that is genuinely in the "Ready for Codify" bucket —
clear acceptance criteria, known scope, satisfied dependencies, enough implementation
detail. If the highest-leverage issue is actually Needs Ideate, Needs Plan, Blocked, or
Duplicate/Superseded, do NOT push on to code. Instead: run the appropriate upstream Spark
stage (/spark:ideate or /spark:plan) to produce the missing framing or scoped sub-issues,
then STOP and report — present the Intake Table, the selection, and the upstream artifact,
and ask before entering Codify. Never manufacture acceptance criteria just to clear this brake.

First action — confirm the repo:

  pwd
  git remote -v
  git status --short
  git branch --show-current

Confirm origin is git@github.com:jwogrady/lawnlord.git (or https equivalent).
If it is NOT jwogrady/lawnlord, stop and ask to be moved into the Lawnlord repo.

Confirm tooling (informational only — NOT a project quality gate):

  gh auth status     # confirm gh is authenticated as jwogrady

Do NOT rely on the standalone `spark doctor` CLI as a signal: it may report a stale
cached version (e.g. 0.2.0) that disagrees with the active 0.3.1 plugin. The Spark
lifecycle is driven by the /spark:* skills, not by the standalone CLI. If the /spark:*
skills are unavailable, continue using the lifecycle manually and say so.

Issue intake:

Inspect Lawnlord open issues first:

  gh issue list --state open --limit 100
  gh issue view <number> --comments    # for each relevant issue

If GitHub CLI is unavailable, use ROADMAP.md, docs/, docs/adr/, TODOs, or provided context —
and say so explicitly. Never pretend GitHub Issues were checked if they were not.

Delegate recon to real subagents (encouraged — this is not role-play):

- Use the Explore agent to sweep issues, ROADMAP.md, docs/adr/, and related source in
  parallel and report back only the conclusions you need.
- Use the Plan agent to draft the implementation plan for the selected issue.
You keep the work ledger and make all selection/advance decisions yourself.

Build an Issue Intake Table with columns:

- Issue number
- Title
- Labels
- State
- Last updated (if available)
- Dependencies / blockers
- Related files mentioned
- Acceptance criteria present? (yes/no)
- Spark stage implied
- Recommended action

Classify every candidate issue into exactly one bucket:

1. Ready for Codify — clear acceptance criteria, scope, dependencies, enough detail.
2. Needs Plan — real problem, but missing scope / criteria / architecture / file impact / order.
3. Needs Ideate — vague desire, unresolved product direction, unclear problem framing.
4. Needs Validate — implementation may already exist; verify against the issue.
5. Needs Ship — work appears complete; needs version / changelog / release / commit / PR / closure.
6. Blocked — depends on another issue, missing state, missing credentials/files, or a prerequisite.
7. Duplicate or Superseded — overlaps another issue or overtaken by newer docs/code.

Issue-selection priority (select ONE issue only), highest leverage first:

1. Unblocks other open Lawnlord issues
2. Establishes reusable platform primitives
3. Improves the v0.4 readiness / QA path
4. Protects the immutable "is" layer
5. Enables analysis proposals / accept-decline flow
6. Enables KB-backed reasoning
7. Enables motion generation
8. Pure docs or cosmetic cleanup

Prefer concrete non-epic issues:

When two candidates are otherwise comparable in leverage, prefer the concrete, narrowly
scoped, single-deliverable issue over an epic, umbrella, meta, or tracking issue. Epics are
containers for work, not work — do not select an epic for Codify. If the top-leverage item
is an epic, drop into its child issues and select the most concrete ready child instead
(and note the parent epic as context).

Do not jump to terminal motion-generation issues until prerequisites are satisfied.

Likely dependency order — treat this as a HYPOTHESIS to validate, not a fact. Your first
job after listing issues is to confirm or REPLACE this order using the actual issue graph,
ROADMAP.md, the ADRs (docs/adr/ already covers exports, divergence/agreement, and spatial
anchoring), and recent git history (#131–#135 show corpus/export/metrics work already
landed). Show the evidence for your chosen order before selecting an issue.

  1. Corpus/export correctness and reconstructable text
  2. QA comparison viewer
  3. Diff/confidence metrics
  4. Page-span spatial anchors
  5. On-image highlight renderer
  6. Knowledge base intake
  7. Accept/decline analysis layer
  8. Ledger and deadline reasoning
  9. Grounds to set aside
  10. Motion generation

Lawnlord doctrine (preserve at every stage):

- The "is" layer (canonical case data) is immutable. Do not mutate canonical case data
  unless the selected issue is explicitly about ingestion/export mechanics.
- Proposals are not truth. Generated analysis stays a proposal unless explicit
  human-accepted state exists.
- Legal conclusions are human-owned.
- Generated legal output is draft-only and review-gated.
- Never fabricate page geometry, citations, legal authority, deadlines, or conclusions.
- Keep Spark methodology out of Lawnlord product docs.

Lifecycle execution:

Maintain ONE work ledger (format below) across the whole run. Move through stages in order,
choosing the correct Spark entry point for the selected issue's bucket:

- Needs Ideate → /spark:ideate, then continue.
- Needs Plan   → /spark:plan (or the Plan agent), then continue.
- Ready/Codify → /spark:codify on a feature branch named from the issue (e.g. feat/<n>-<topic>).
- Validate     → /spark:validate (runs /code-review + /security-review + verify, fixes findings).
- Ship         → /spark:ship: conventional commit, push branch, open one focused PR.

Keep README.md, CHANGELOG.md, ROADMAP.md, docs/ux.md, and docs/adr/ aligned whenever
behavior, workflow, roadmap status, or architecture changes. Record an ADR for real
architecture decisions (next number is 0010).

Work ledger format (maintain throughout):

## Work Ledger
- [ ] Confirmed repo is jwogrady/lawnlord
- [ ] Lawnlord GitHub Issues inspected
- [ ] Dependency-order hypothesis validated against issues/ROADMAP/ADRs/git log
- [ ] Issue Intake Table produced
- [ ] One issue selected (with reasoning)
- [ ] Correct Spark entry point chosen
- [ ] Ideate complete if needed
- [ ] Plan complete if needed
- [ ] Feature branch ready
- [ ] Codify complete
- [ ] README updated if needed
- [ ] CHANGELOG updated if needed
- [ ] ROADMAP updated if needed
- [ ] ADR/docs updated if needed
- [ ] Validation passed (/spark:validate)
- [ ] Security review passed (/security-review)
- [ ] Lawnlord doctrine check passed
- [ ] Commit prepared (conventional, <=72 char subject, no AI attribution)
- [ ] PR opened, issue referenced or closed correctly

Validation contract (verify before shipping):

- active repo is jwogrady/lawnlord
- selected GitHub Issue was read; implementation matches it
- no unrelated issues were pulled in
- relevant tests/checks pass
- touched shell scripts pass `bash -n`
- docs accurately describe current behavior; README/CHANGELOG/ROADMAP/ADRs updated when required
- no direct trunk commit; no force push; no fake claims; no stale roadmap claims; no AI attribution
- acceptance criteria are satisfied
- immutable "is" layer remains protected
- proposals remain proposals unless accepted by explicit human-owned state
- legal conclusions remain human-owned; generated legal output is draft-only and review-gated

PR body template:

## Summary
What changed and why.

## Issue
Closes #<issue-number>   <!-- use "Refs #<issue-number>" if this does not fully close it -->

## Spark Stage
Ideate → Plan → Codify → Validate → Ship

## Changes
-
-

## Validation
- [ ] /spark:validate (code-review + security-review + verify) clean
- [ ] relevant tests/checks
- [ ] docs reviewed
- [ ] acceptance criteria met
- [ ] Lawnlord doctrine check passed

## Docs
- README:
- CHANGELOG:
- ROADMAP:
- ADRs:
- Other docs:

## Risk
Risk level and rollback path.

Start now:

1. Confirm you are in jwogrady/lawnlord.
2. Inspect open Lawnlord issues.
3. Validate (or replace) the dependency-order hypothesis with evidence.
4. Produce the Issue Intake Table.
5. Select exactly one issue and explain why.
6. Choose the correct Spark entry point and run the full loop through to an open PR.

Do not start coding until the Issue Intake Table exists and exactly one issue has been selected.

Never credit yourself. Only credit the author: jwogrady.
