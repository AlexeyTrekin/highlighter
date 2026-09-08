# SPECIFICATION GUIDELINES
1. NEVER change specifications unless explicitly and separately asked to work on them. If some specification produces suboptimal code, raise it in the WAL motivation and surface to the user during the Confirmation Gate or Review Loop.
2. Tests MUST directly follow SPECIFICATION found in /spec folder. If some test is impossible to write according to specification, STOP ITERATION and ask user.
3. Application code SHOULD follow specifications unless impossible; in this case STOP ITERATION and ask user before deviating.

# GIT COMMAND POLICY FOR AGENTS

Assume the agent-security-toolkit is installed and the repo is onboarded (`agent-repo-init` already run). Use `agent-git` for every git operation. Raw `git` is not recommended and almost always requires manual approval; reach for it only when the task genuinely needs an operation `agent-git` does not expose, and state the justification in the command text.

## What `agent-git` enforces (do not try to bypass)
- Push only from branches prefixed `feature/`, `fix/`, `chore/`, `refactor/`, `test/`, `agent/`.
- Never pushes to `main`, `master`, `develop`, `release/*`, `hotfix/*`.
- Blocks `--force`, `-f`, `--mirror`, `--all`, `--prune`, `--delete`, `-d`, `--tags`, `--follow-tags`.
- Blocks `git rm -r`, `git reset --hard`, `git config` writes, and reads of `agent-*.*` / `core.hooksPath` (so don't probe).
- `fetch`/`pull` accept only `origin`.
- `git clone`, `git init`, `git remote …`, `git submodule …`, `git worktree …` are not exposed — escalate to the user if you need them.
- Commits are signed with the bot identity from `/etc/agent-security-toolkit.conf`. **Do NOT add `Co-Authored-By:` trailers — the bot account IS the agent attribution.**

## What `agent-git push` does for you (do not duplicate)
On the **first** push of a branch (the branch does not yet exist on `origin`), `agent-git`
automatically adds:
- `--set-upstream` (wires up tracking)
- `-o merge_request.create`
- `-o merge_request.draft`
- `-o merge_request.target=<policy>` — the target comes from per-repo `agent-git.mr-target`; **agent-supplied `merge_request.target=` is rejected**.

On **subsequent** pushes (the branch is already on `origin`), `agent-git` sends a plain
push and adds **none** of the `merge_request.*` options. This is deliberate: re-sending
`merge_request.draft` on every push would flip an MR a reviewer marked **Ready** back to
**Draft** — which, on repos that skip pipelines for draft MRs, silently disables CI for
your latest commit. So the draft/ready state you (or a reviewer) set is left untouched.

So the entire MR-open flow is one command:
```
agent-git push
```
By default GitLab uses the **last commit subject** as the MR title. Override at first open by passing the title explicitly:
```
agent-git push -o merge_request.title="add review loop and language packs"
```

## Modifying the MR header on follow-up pushes
`agent-git` no longer touches the MR's draft/ready state on follow-up pushes, but you can
still change the title or body without the UI by passing the options **explicitly** — they
are applied to the existing MR:
```
agent-git push \
  -o merge_request.title="new title" \
  -o merge_request.description="updated summary…"
```
The only push options `agent-git` accepts: `merge_request.create`, `merge_request.draft`, `merge_request.title=…`, `merge_request.description=…`. Anything else (including `merge_request.target=…`) is rejected by policy.

## When `agent-git` blocks you
Read the `agent-git BLOCKED:` line — it is the spec. **Do not work around it.** Stop and surface to the user with the exact message. Common cases:
- Branch name doesn't match the allowed prefix → rename the branch.
- MR target equals current branch → user must run `agent-repo-init --mr-target <branch>`.
- Push to protected branch → switch to a feature branch first.
- Watched-file mismatch from `agent-make` → see make policy below.

# MAKE COMMAND POLICY FOR AGENTS

Use `agent-make` for every build / test / lint invocation in this repo. Raw `make` usually requires manual approval and bypasses the watched-file verification.

The project runs directly on the host (`spec/004_stack.md`). `agent-make` targets drive a
local virtualenv (`.venv/`) and host tools (`ffmpeg`, `ffprobe`), and `agent-make doctor`
is what verifies those tools are present before a stage needs them.

## Usage
- `agent-make <target> [<target>…]` — root Makefile (`agent-make test`, `agent-make lint test`).
- `agent-make --in <subdir> <target>` — monorepo sub-Makefile (the sub-Makefile must be covered by the watched-files list — a literal entry or a glob that matches it).
- Targets must be plain identifiers (`[A-Za-z0-9._/-]+`). No flags, no shell metacharacters.
- `VAR=val` overrides (e.g. `agent-make itest SERVICE=inference`) are allowed **only** for variable names a human listed in `agent-make.allowed-vars`, with values matching `agent-make.var-pattern` (a metacharacter-free charset). If the variable you need isn't allowlisted, STOP and ask the user to add it — don't work around it.

## What `agent-make` enforces
- Fetches `origin/<protected branch>` and verifies every watched file (here: `Makefile`) byte-for-byte against the remote before running. **Any local modification to a watched file blocks every `agent-make` invocation.**
- `agent-make.files` may use globs (`services/*/Makefile`); every path a glob matches is verified the same way, so a new sub-project is covered as soon as its Makefile exists.
- Optional per-repo target allowlist (`agent-make.allowed-targets`) — unlisted targets are blocked.

## When `agent-make` blocks you
- *"local files differ from origin/<branch>"* — the message names the exact file(s). A watched file was edited locally. **STOP and surface to user.** The fix is human-only: merge the change into the protected branch via normal MR review, then continue. Do not revert other agent work to satisfy this check.
- *"Target 'X' is not in agent-make.allowed-targets"* — STOP and ask the user to extend the allowlist via `agent-repo-init --allowed-targets …`.
- *"VAR=val overrides are not enabled"* / *"Variable 'X' is not in agent-make.allowed-vars"* — STOP and ask the user to allowlist it via `agent-repo-init --allowed-vars …`.
- *"Sub-Makefile '<path>' is not covered by agent-make.files"* — STOP and ask the user to add it (or a matching glob) via `agent-repo-init --files …`.

# ENFORCED COMMAND BOUNDARY

The two policies above are the whole boundary, and `.claude/settings.json` enforces them
mechanically so an agent cannot cross it by accident:

- **Version control** → `agent-git` only. Raw `git` is denied.
- **Build, test, lint** → `agent-make` only. Raw `make` is denied.
- **Running the application** → the project's own entry point, `.venv/bin/hlreel …`
  (`spec/009_agent_surface.md`). This is app usage, not a build step, so it does not go
  through `agent-make`.
- Denied outright: raw `git`, `make`, `sed`, `awk`, `curl`, `wget`, `rm`, `mv`, and
  system-wide `pip`/`python`.

When a command you need is denied, that is a decision, not an obstacle: stop and surface it
with the exact block message rather than looking for another route to the same effect.

# PROJECT STRUCTURE AND ADDRESSING
- Makefile: venv bootstrap, test, lint and run — the only supported entry point (via `agent-make`)
- /spec: contains specifications, ordered by hierarchy: the very foundation in 001, then go the most important architecture details (api, db, stack), all further decisions and rationale are documented in subsequent files
- /app: application code
- /tests/unit, /tests/it - unit- and integration- tests
- .data/ - **gitignored** local media: source footage and music tracks used for real-footage validation. Never committed, never uploaded.
- WAL.md - persistent journal of completed steps and the WHY of each decision. Distilled, committed, survives across branches.
- .plans/ - **gitignored** per-branch agent handover scratchpad. One file per feature branch: `.plans/<sanitized-branch-name>.md` (slashes in the branch name become dashes, e.g. `feature/foo-bar` → `.plans/feature-foo-bar.md`). Holds the detailed step plan, stabilization discoveries, push-back rounds, and Final Review Summary. Never reaches the remote; the distilled motivation lands in WAL.md at merge.

# SESSION PROTOCOL FOR FEATURE IMPLEMENTATION
Execute it every time a session is initiated.

0. Ensure local master is up to date: `agent-git checkout master && agent-git pull --ff-only`.
    - If there are unstaged/uncommitted changes, STOP ITERATION and ask user how to proceed.
1. Read WAL.md to update the state of the previous steps to revisit decision making (`instructions/planning.md`)
2. planning.md: Find next step to work on in WAL.md (`instructions/planning.md`)
3. planning.md: Revisit `/spec` folder for the documentation related to the task. Use `/spec/index.md` to find related documents, then dive into them (`instructions/planning.md`).
    - If contradictions are found, STOP ITERATION, ask user to clarify spec and task, and highlight inconsistent documentation.
4. planning.md: Specification coverage gate (`instructions/planning.md`):
    - If needed behavior is not fully covered by existing specs, propose spec delta in chat.
    - Modify/add spec files only after explicit user approval.
    - If a new spec document is added, update `/spec/index.md` accordingly.
5. planning.md: Plan execution in more detail (in session chat) (`instructions/planning.md`).
6. **Confirmation gate** — MANDATORY (`instructions/planning.md`):
    - STOP and present the plan to user. Do NOT proceed to git management or implementation until user explicitly confirms.
    - The plan must include: scope, spec references, assumptions, and implementation steps.
    - Wait for user approval. If user requests changes, revise the plan and re-present.
7. planning.md: Write detailed implementation plan to `.plans/<branch>.md` for handover (gitignored — slashes in the branch name become dashes, e.g. `feature/foo-bar` → `.plans/feature-foo-bar.md`). This file is the implementer/stabilizer scratchpad; it never reaches the remote.
8. Git management (`AGENTS.md`) — MUST happen before ANY file edits:
    - Check repository state with `agent-git status --porcelain`.
    - If there are unstaged/uncommitted changes or conflicts, STOP ITERATION and ask user how to proceed.
    - Refresh `master` branch with `agent-git checkout master && agent-git pull --ff-only`.
    - Create a feature branch with `agent-git checkout -b feature/<feature_name>`.
    - **No file may be created, edited, or deleted before this step completes successfully.**
9. delivery.md: Implement the plan (`instructions/delivery.md`). Typical implementation order:
    - tests;
    - code;
10. stabilization.md:
    - run tests;
    - if tests pass, continue;
    - if tests fail, use delivery.md to iterate on code changes; and test execution until tests pass or you are blocked (`instructions/stabilization.md`).
    - write discoveries to `.plans/<branch>.md`
11. **Review loop** (`instructions/review.md`):
    - Bounded cycle (`MAX_REVIEW_CYCLES = 2`) of: review → push-back protocol → implementation fixes → stabilization on fixes → re-review.
    - Reviewer has final say within the loop; the second push-back on a confirmed CRITICAL escalates to user. Every push-back round is logged in the Final Review Summary.
    - Early stop & escalate (token-budget aware): plan/spec change required, per-cycle caps exceeded, repeated CRITICAL signature, cycles exhausted with CRITICAL still open.
    - Reviewer inputs are limited to WAL.md, spec files referenced by the step, and the diff — the reviewer MUST NOT read `.plans/<branch>.md` (reading the implementer's step-by-step biases review toward plan-compliance instead of spec-compliance).
    - Reviewer appends Final Review Summary to `.plans/<branch>.md` before exit (fixed / push-backs accepted / push-backs confirmed / deferred / open questions / escalation reason if any) AND prints the summary in chat.
    - On escalation, STOP ITERATION and present the summary to user; do NOT proceed to step 12.
12. Pre-merge WAL update (`AGENTS.md`):
    - Update WAL step status to `[ready-for-review]` with concise motivation.
    - Distil important insights from `.plans/<branch>.md` into the WAL.md motivation line. The `.plans/` file itself stays local — gitignored, no cleanup needed.
13. Commit, publish branch, and open Draft MR (`AGENTS.md`):
    - Commit work with a meaningful message — the subject doubles as the default MR title.
    - Publish branch and open the Draft MR in one shot:
      ```
      agent-git push
      ```
    - On the **first** push of a branch, `agent-git push` automatically adds `--set-upstream`, `merge_request.create`, `merge_request.draft`, and the policy-controlled `merge_request.target`. Do NOT supply them manually — explicit `merge_request.target=…` is rejected. Follow-up pushes send a plain push and do **not** re-draft the MR.
    - To pin a different MR title at first open: `agent-git push -o merge_request.title="…"`.
    - For follow-up pushes (review-loop fixes, stabilization, header updates), see the FULL LOOP EXAMPLE section below.
14. MR review and merge decision gate (in chat) (`AGENTS.md`):
    - Wait for user to confirm review outcome (`approved`, `changes requested`, or `merged`).
    - If `changes requested`: address feedback, push to the same MR, keep WAL status `[ready-for-review]`.
    - If `approved`: 
    -- update WAL step status to `[v]`. 
    -- create a follow-up commit for WAL update, and `agent-git push`. Then wait for user to merge.
    -- `.plans/<branch>.md` is gitignored — no removal step needed; it stays on the local machine and is naturally orphaned when the branch is deleted.
    - If `merged` (user merged directly without separate approval): update WAL step to `[v]` on master (see step 15).
15. Post-merge finalization (`AGENTS.md`):
    - If WAL was already updated to `[v]` in the MR (approval path): nothing to do, WAL is correct on master after merge.
    - If user merged without prior approval signal: `agent-git checkout master && agent-git pull --ff-only`, mark WAL step `[v]`, commit and push directly to master using `agent-git push`.

# IMPLEMENTATION DEFINITION OF DONE (PRE-MERGE)
- tests added/updated according to the feature specification
- `agent-make test` runs successfully
- review loop converged (0 open CRITICAL) or was explicitly escalated to user with Final Review Summary
- branch pushed and `[Draft]` MR created
- WAL step is updated to `[ready-for-review]` with concise motivation

# APPROVAL DEFINITION OF DONE (PRE-MERGE)
- user confirms `approved` in chat
- WAL step is updated to `[v]` in the MR branch, pushed
- user merges the MR

# WORKFLOW DEFINITION OF DONE (POST-MERGE)
- MR is merged (WAL step already `[v]` from approval step)
- master is up to date

# COMPANION INSTRUCTIONS (SCOPED)
- `instructions/planning.md`: use for strategic planning and architecture decisions in `spec/**`.
- `instructions/delivery.md`: use for feature/fix delivery (methodology only — no language-specific style).
- `instructions/stabilization.md`: use when tests fail, CI is red, or user review requests iterations.
- `instructions/review.md`: use after stabilization for the bounded review loop on the staged diff.
- If multiple companion instructions seem relevant, prioritize by phase: `planning` -> `delivery` -> `stabilization` -> `review`.
- These companion files augment this `AGENTS.md`; they do not override specification requirements.

# LANGUAGE PACKS (SCOPED)
- `instructions/lang/python.md`: Python conventions (PEP 8, module-function pattern, JSON-manifest persistence, venv-based tests). Applies to `{app,tests}/**`.
- Add packs for other languages under `instructions/lang/` as the project grows. Each pack declares its own scope via `applyTo:` frontmatter.
- During delivery, stabilization, and review, consult the pack(s) matching the files being touched. If no pack covers a language present in the diff, ask the user before inventing conventions.

# OPTIONAL: PER-PHASE MODEL SELECTION (CLAUDE CODE)
- When running under Claude Code, each phase MAY be delegated to the corresponding subagent in `.claude/agents/` (`planner`, `implementer`, `stabilizer`, `reviewer`). Subagents pin a recommended model per phase and reference the same instruction files.
- The main agent stays as orchestrator: it drives the session protocol above and dispatches each phase to the matching subagent.
- In environments without subagent support (Copilot, generic agents), ignore `.claude/agents/` and execute the instruction files inline — the workflow is unchanged.

# WAL MOTIVATION EXAMPLES
*Illustration — substitute your stack. The pattern (motivate the WHY, not the WHAT) is language-agnostic.*

BAD EXAMPLE (describes WHAT, which is already obvious from code). Don't do this.
```
[v] Implement request to external service
Used aiohttp; set the number of connections to 20
```
GOOD EXAMPLE:
```
[v] Implement request to external service
aiohttp is better than httpx for high throughput
limited connections to avoid server DDoS protection, issues can start around 40 connections
```

# COMMANDS TO RUN
All build/test invocations go through `agent-make` (raw `make` requires manual approval per call and bypasses watched-file verification).

`agent-make doctor` — check host prerequisites (python, ffmpeg with libvidstab, ffprobe)
`agent-make venv` — create/refresh `.venv/` and install the project with dev extras
`agent-make test` — full test suite
`agent-make utest` — unit tests only
`agent-make itest` — integration tests only
`agent-make lint` — ruff check + format check
`agent-make fmt` — ruff format (writes)
`agent-make run` — start the review server on the host (arrives with WAL step 3.1)
`agent-make bench` — score candidate ranking against recorded human verdicts (WAL step 2.2)
`agent-make clean` — remove `.venv/`, caches and build artifacts

`run` and `bench` are wired ahead of the CLI commands they call, because `agent-make`
verifies the `Makefile` against `origin/master` and a later edit would block every branch
until it is merged. Until those WAL steps land they fail with `No such command`.

All targets depend on `venv` where they need it, so a fresh checkout only needs
`agent-make test`. If `agent-make` blocks with *"local files differ from origin/master"*,
the `Makefile` was edited locally — escalate to the user. Do not undo other work to satisfy
the check.

Note: `agent-make` accepts `VAR=val` overrides only for variables a human listed in `agent-make.allowed-vars` (this repo lists none, so any `VAR=val` is rejected here). Add a dedicated target instead of reaching for a variable.

# TERMINAL COMMAND BATCHING
- Read-only commands (`agent-git status`, `agent-git diff`, `agent-git log`, `agent-git show`, etc.) are allowlisted — call them directly, don't batch.
- Combine state-changing commands into a single `&&`-chained invocation when there is no need to inspect intermediate output. Example after a Confirmation-Gate-approved task with a clear path list:
  ```
  agent-git add app/foo.py tests/unit/test_foo.py && \
    agent-git commit -m "feat: foo handles empty input" && \
    agent-git push
  ```
- Prefer explicit paths over `agent-git add -A` / `add .` so untracked secrets or scratch files do not slip in. Use `-A` only when you have just run `agent-git status` and confirmed every untracked path belongs in the commit.
- Preferred fixup flow: new commit + `agent-git push`. Amend / force-push are blocked by `agent-git` by design.
- Raw `git push --force-with-lease` is blocked and should not be attempted — surface to user if you genuinely need it.

# FULL LOOP EXAMPLE — START TO MR
Concrete copy-paste of every step. The exact flow the SESSION PROTOCOL above expects.

```bash
# 0. Fresh start from the protected branch
agent-git checkout master
agent-git pull --ff-only

# 1. Investigate recent history before planning
agent-git log --oneline -20                        # recent commits
agent-git log --oneline master..origin/master      # what landed since last sync
agent-git show <sha>                               # inspect a specific commit
agent-git diff <sha>~..<sha> -- path/              # narrow diff for a file/dir
agent-git blame path/to/file.py                    # who/why on a specific line

# 2. After the Confirmation Gate (step 6): create the work branch
agent-git checkout -b feature/short-descriptive-name

# 3. While working: track changes incrementally
agent-git status
agent-git diff                                     # unstaged changes
agent-git diff --staged                            # staged changes
agent-git log --oneline -5                         # commits on this branch

# 4. Stage explicit paths, then commit
agent-git add app/foo.py tests/unit/test_foo.py
agent-git commit -m "feat: foo handles empty input"
# The commit subject becomes the default MR title.

# 5. Open the Draft MR in one command
agent-git push
# Optional: pin the MR title at open instead of inheriting commit subject
agent-git push -o merge_request.title="feat: foo handles empty input"

# 6. Follow-up commit (review-loop fix, stabilization, etc.) — same flow
agent-git add app/foo.py
agent-git commit -m "fix: address review comment about N+1 query"
agent-git push                                     # GitLab updates the existing MR

# 7. Update MR header on a follow-up push (no UI needed)
# IMPORTANT: git rejects newlines in push-option values with
#   fatal: push options must not have new line characters
# So MR title and description passed via -o must each fit on a single line.
agent-git push \
  -o merge_request.title="feat: foo handles empty input + N+1 fix" \
  -o merge_request.description="Summary: foo accepts empty input; batched prompt fetch removes N+1. Test plan: agent-make utest && agent-make itest."

# For a rich, multi-line MR description, do NOT try to cram it into a
# push option. Instead, put the body into the commit message itself —
# GitLab uses the commit body as the MR description by default whenever
# you do not override it with -o merge_request.description=.
agent-git commit -m "$(cat <<'EOF'
feat: foo handles empty input + N+1 fix

## Summary
- foo accepts empty input without raising
- batched the prompt fetch to remove N+1 query

## Test plan
- agent-make utest
- agent-make itest
EOF
)"
agent-git push   # at MR open: title = commit subject; description = commit body
                 # (on follow-up pushes GitLab keeps the existing title/body unless
                 #  you pass -o merge_request.title=/description= explicitly)
```

Hard rules surfaced again here:
- `agent-git push` opens a Draft MR on the first push of a branch and just moves commits on later pushes (it will not re-draft an MR a reviewer marked Ready) — never call `gh`, `glab`, or `git push -o merge_request.target=…` yourself.
- `--set-upstream` is added automatically; do not pass `-u`.
- No `Co-Authored-By:` trailers — the bot account identity is the agent attribution.
- Only `merge_request.{create,draft,title,description}` push options are accepted by `agent-git`; anything else is rejected.
- Push-option values are **single-line only** — git rejects newlines. For multi-line MR descriptions, write them into the commit body and push without `-o merge_request.description=`.

# WHERE THE WHY GOES

Three places hold three different kinds of "why" — keep them separate. Putting the wrong
kind in the wrong place is how comments turn into stale, back-facing narration.

- **Code comments** → the *present-tense constraint* a first-time reader needs to not break
  the code (a forward-facing rule, not a changelog). They never reference a previous state
  or defend normal code. Full discipline in `instructions/delivery.md` COMMENTS DESCRIBE THE
  CODE, NOT ITS HISTORY.
- **Commit message** → the *historical why*: what this change does, what it replaced, and
  the hazard the old form carried. This is the home for every "used to / previously / no
  longer" fact. It stays attached to the diff that made the change and never rots into the
  code.
- **`WAL.md`** → the *step-level motivation and status* for the workflow (why this step
  exists, acceptance criteria, ready-for-review state). See WAL MOTIVATION EXAMPLES.

Rule of thumb: if a fact only makes sense to someone who saw the diff, it belongs in the
commit message, not a comment.

# IMPLEMENTATION GUIDELINES
- Methodology: `instructions/delivery.md` (includes COMMENTS DESCRIBE THE CODE, NOT ITS HISTORY).
- Language style: matching pack under `instructions/lang/` (e.g. `lang/python.md` for `{app,tests}/**`).
