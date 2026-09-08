# WAL — Tournament Highlight

Working journal. One entry per completed step. Record the **WHY** of each
decision, not the WHAT (the code already shows the what). Distilled, committed,
survives across branches.

Status markers: `[ ]` planned · `[ready-for-review]` done, in MR · `[v]` merged.

## Phase 0: Foundation

### 0.1 De-dockerize the agent instructions, write the spec set, host build
[v] Remove every container rule from `AGENTS.md`, `instructions/lang/python.md` and the
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
[ready-for-review] ingest → probe → naive candidates → fitted music grid → naive EDL → render,
plus the five structural rules the prototype's defects exposed.

Value comes from a watchable reel, not from a good one. Getting the whole path working with
deliberately dumb selection makes every later quality change measurable against something,
and surfaces the render-stage hazards while the pipeline is small enough to debug.

The prototype's v2/v3 reels were analysed rather than trusted, and three user-reported defects
turned out to have two causes:

**Tempo.** librosa 1.0.0 measures 120.19 BPM prior-independently where the prototype recorded
117.45. The drums enter at 12.196 s; the 120.19 grid puts that bar line at 12.19 s, the
117.45 grid at 12.49 s. That 0.3 s is why a quiet intro clip ran into the drums, and the
error accumulates — by the outro it is over a second, which is why the fade landed on an
action clip instead of a coda. Two complaints, one root cause. The old number is superseded,
not a target to reproduce.

**Slots longer than their source.** v42 has 3.74 s and was given a 4.09 s slot; v31 has
3.10 s. The renderer reached past end-of-file and repeated the last decoded frame — the two
freezes the user saw. The fix is a candidate gate, not a renderer fallback: shortening the
clip instead would break the bar grid for everything after it. Rendering now refuses to emit
a frame it did not decode, so this fails loudly rather than shipping.

The remaining complaint — a cut at bar 3 of a six-bar intro, where nothing happens musically —
drove hierarchical section detection. The sub-band steps ×1.7 at bar 1 and ×43 at bar 6; one
threshold catches the second and is deaf to the first, though a listener hears both. Cut
points are now ranked (major boundary > minor > plain bar), and material must match section
character, because an action clip in a drumless intro reads as a mistake however well it is
aligned.

Two things surfaced during implementation that the analysis had not predicted:

**Downbeat phase cannot be voted for.** Scoring candidate phases by onset strength — the
prototype's method and the obvious one — picked beat 4 of the bar on this track, because a
metal backbeat is louder than its kick. Low-band-only onsets did no better. The phase is now
anchored on the detected drum entry, which is a downbeat in almost any arrangement.

**A grid check must not test the thing it was fitted from.** Validating bar lines against the
drum entry became circular once that entry anchors the phase. The check now tests the
*period* against a least-squares fit of the tracked beats, which is the half that drifts. Its
first honest form — RMS distance from each beat to a rigid grid — condemned a correct grid at
102 ms, because beat positions wander by a frame or two on any real track and that wander
accumulates. A measure that fails a correct grid is worse than no measure.

**The inherited brightness check was wrong.** The prototype flagged any frame-to-frame
brightness change above 12, and on the first real render that failed a good reel: one clip
pans into bright sky, moving +17.7 then +14.3 in the same direction. The artifact it exists to
catch is a *spike* — a frame that departs from both neighbours and reverts — so the rule now
requires exactly that. Across the other fourteen clips the worst frame-to-frame move was 3.9,
so the tightened rule has plenty of headroom.

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
