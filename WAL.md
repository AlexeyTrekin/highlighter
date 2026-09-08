# WAL — Tournament Highlight

Working journal. One entry per completed step. Record the **WHY** of each
decision, not the WHAT (the code already shows the what). Distilled, committed,
survives across branches.

Status markers: `[ ]` planned · `[ready-for-review]` done, in MR · `[v]` merged.

## Phase 0: Foundation

### 0.1 De-dockerize the agent instructions, write the spec set, host build
[ready-for-review] Remove every container rule from `AGENTS.md`, `instructions/lang/python.md` and the
subagent definitions; add `spec/001`–`spec/009`; add `Makefile`, `pyproject.toml`, the
`hlreel doctor` command and a first test.

No container: this is a local media tool whose heavy dependency (ffmpeg) is a system package
either way, and whose optional accelerated backends need the machine's GPU directly. An image
would buy isolation we do not need and cost a media mount and device passthrough. The price
is that reproducibility now rests on `agent-make doctor` — hence the prerequisite check
existing before any pipeline code.

The spec set is written from a working prototype rather than from scratch, so it records
decisions that were *measured* (fitted BPM, camera compensation, crop-flash invariant) and
marks the rest as open. `002_manifests.md` is the load-bearing document: the project
directory is the state, and `edl.json` is the contract the renderer is a pure function of.

The `Makefile` lands now rather than with the first pipeline branch because `agent-make`
verifies it byte-for-byte against `origin/master` and blocks every invocation while they
differ — no later branch can run tests until it is merged. For the same reason its target set
is complete ahead of the code: `run` and `bench` call CLI commands that arrive in steps 3.1
and 2.2, and fail until then. Paying one human-reviewed merge now beats paying one per target
later.

## Phase 1: Walking skeleton

### 1.1 End-to-end reel with naive selection
[ ] ingest → probe → naive candidates → fitted music grid → naive EDL → render.

Value comes from a watchable reel, not from a good one. Getting the whole path working with
deliberately dumb selection makes every later quality change measurable against something,
and surfaces the render-stage hazards (cumulative rounding, crop flash) while the pipeline is
small enough to debug.

## Phase 2: Good moments

### 2.1 Camera-compensated activity, halt detection, closing speed
[ ] Replace frame-diff energy with compensated flow; anchor windows on the halt; add
pose-based closing speed behind an optional backend.

### 2.2 Benchmark against recorded human verdicts
[ ] `hlreel bench` reporting rank agreement on the 69 windows with known agent and user
verdicts.

Reported metric with a regression floor, not a pass/fail assertion: a scorer that reproduces
one person's taste exactly is overfitted, and an equality test would flag every legitimate
improvement as a failure.

## Phase 3: Human loop

### 3.1 Proxies, filmstrips, review server and UI
[ ] 360p proxies and contact sheets; the local review server; three-state verdicts, trims and
ordering; `review.json` consumed by the director.

## Phase 4: Musicality

### 4.1 Sections, mood, clip↔section matching
[ ] Section table with per-section energy; director rules that place the drop, the build and
the coda.

## Phase 5: Personal highlights

### 5.1 Kit clustering, target confirmation, target-aware scoring
[ ] `identity.json`; one-click confirmation view; `target_side` feeding scoring and framing.

## Phase 6: Long recordings

### 6.1 Pre-pass, bout segmentation, halt-driven exchange detection
[ ] The `shape == "long"` path end to end.

## Phase 7: Agent surface

### 7.1 MCP wrapper, final-tweaks view, VLM candidate re-ranker
[ ] MCP over the same module functions; EDL-over-waveform editing; optional vision scorer.
