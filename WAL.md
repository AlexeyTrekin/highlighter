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
[v] ingest → probe → naive candidates → fitted music grid → naive EDL → render,
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
[v] Person detection, camera-compensated activity, halt-anchored windows, quality gates, a
configurable composite score, and material classification. New `analyze` stage: the only one
that decodes whole videos, so everything downstream reads `analysis/vNN.json` instead.

**A baseline must be the resting level, not the median.** The first halt detector took "settled
below the clip's baseline" to mean the median and found no halts at all. A clip is mostly *not*
fencing — approach, reset, the referee talking — so its median sits at the resting level and
nothing can fall below it. Settling is now measured against the clip's own 25th-to-95th
percentile range, which is also what makes the test scale-invariant across distance and light.

**Material classification cannot use motion, and the first attempt did.** A rule keyed on how
much movement there is called every calm window "fencing measured from slightly further out" —
because a hug is vigorous and a salute can include a clash. What separates them is what the
*distance between the fighters* does: fencing closes to hit and breaks to reset, an embrace
comes together and stays, a walk-on holds its distance. Two features carry it — the gap's
interquartile range and how often it crosses into measure.

`unknown` is a third verdict rather than a placeholder. Fencing is a continuum; a window near
the thresholds is genuinely undecided, and forcing it is how a lunge lands under a still chord
behind a green check.

**A halt-anchored stage can only propose exchanges.** Warm-ups, salutes and walk-ons produce
no halt, so the drumless intro had nothing honest to draw on however good the classifier was.
Stable-gap windows were added, and then solo windows on top: measuring a gap needs two
fighters, so a one-person walk-on has no gap to hold steady and stable-gap detection could
never find one. The collection holds four such runs; three reached the reel.

**Known limitation.** Stable gap cannot separate an embrace from point-fencing at long
measure — both hold their distance, and on this footage the highest-scoring "calm" windows
were the latter. The director works around it by ordering quiet slots by fewest fighters on
camera rather than by score, which is a preference, not a fix. Separating those two properly
needs a signal this build does not have: blade tracking, or a vision model on the frames.

**Recordings open mid-action, and that cost real exchanges.** On the real footage the halt
detector fired one second into 28- and 31-second clips — genuine halts, because the camera
comes up on an exchange already under way. Two consequences, fixed separately: a fall with no
action before it is not a halt at all (a quiet opening was producing them), and a long source
now spends its three-window budget only on windows long enough to be cut. Before the second
fix an unusable one-second window displaced a real exchange later in the same clip. Usable
windows went from 45 to 54.

**Letterbox, not stretch.** The prototype squashed 16:9 into the detector's square input.
Since the fighter test is box height as a fraction of frame height, a distorted aspect ratio
corrupts exactly the measurement it feeds.

**Spectators were being promoted to fighters.** Taking the two tallest boxes over 22 % of frame
height sounds sufficient until you measure the crowd: fighters run 52-56 %, spectators 20-27 %.
Whenever a fighter left frame the next-tallest bystander filled the slot, so "both fighters
visible" was true in every window of every clip — useless precisely when it mattered. Fighters
stand at the same distance from the camera and so appear the same height, so the second box
must now be at least 60 % of the tallest. Two-fighter frames fell from 99 % to 84 %, which is
what made walk-ons visible at all.

**The coda rule became implementable.** With clips classified, `fade_target` stopped saying
"material unknown" and started reporting a real defect — the outro fade covering a fight clip,
which is exactly what the user objected to in v3. The director now prefers non-fight material
for the fade. Preferred rather than required, unlike the drumless intro: an action clip under
a quiet opening is jarring, whereas under a fade-out it is merely a wasted finale, and
truncating the reel to avoid one would be the worse trade.

Weights live in `project.json` rather than in code because they are the thing the benchmark
tunes. Left untuned here: several windows saturate the activity scale and score 1.000, which
compresses the top of the ranking. Fixing that by eye would be fitting to an invented number;
2.2 measures it against the recorded verdicts instead. Model weights are fetched, not committed: they are large and not ours to redistribute,
and `hlreel fetch-models` is the only command that touches the network.

The pose backend for `closing_speed` is deliberately not built. The spec declares it optional
and specifies a box-centre fallback; shipping the free version first lets 2.2 say whether pose
earns a GPU dependency instead of assuming it does.

### 2.2 Benchmark against recorded human verdicts
[ ] `hlreel bench` reporting rank agreement on the 69 windows with known agent and user
verdicts.

Reported metric with a regression floor, not a pass/fail assertion: a scorer that reproduces
one person's taste exactly is overfitted, and an equality test would flag every legitimate
improvement as a failure.

## Phase 3: Human loop

### 3.1 Proxies, filmstrips, review server and UI
[ready-for-review] 360p proxies, posters and filmstrips; the local review server; three-state
verdicts and trims; `review.json` consumed by the director.

Ordering is split into 3.2 rather than bundled here: it is a separate UI surface
(drag-to-sequence, opening and ending buckets, weights) with a non-trivial director side,
since a pinned position is binding and an unhonourable pin must surface a conflict. Verdicts
and trims already close the loop end to end.

**Operating the page found what testing it did not.** Every API test passed against a grid of
55 black rectangles: a `<video>` with `preload="metadata"` renders nothing until played, so
the page was useless for the one thing it exists for — seeing fifty clips at once. Posters are
now built alongside the proxies, and the videos load nothing until hovered.

**A trim binds; a reach-back does not respect it.** A clip is anchored at its window end and
reaches back the length of its slot, which is right for a detected exchange — the reach-back
is the approach. For a human trim it is wrong: they said which seconds they wanted, and
reaching past the start puts back the footage they just removed. Same shape as the calm-window
defect from 2.1's review, and found the same way, by watching what the director actually did
with a window someone had narrowed.

**A keep that cannot be honoured is now reported.** Marking a clip keep and trimming it below
the shortest slot made it vanish from the reel in silence. A keep is the strongest signal the
pipeline gets; one that quietly fails to appear is the worst outcome available, because a
decision was made, the reel ignored it, and nothing said so.

`duplicate_footage` became implementable here: it needed a coarse per-source thumbnail, which
nothing recorded. A checksum would not do — a clip re-uploaded through a messenger is
re-encoded, so every byte differs while the picture is identical.

### 3.2 Ordering: strict sequence, weights, opening and ending buckets
[ ] Drag-to-sequence UI; pinned positions binding on the director; conflicts surfaced rather
than quietly resolved.

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
