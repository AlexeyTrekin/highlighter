# 005 — Finding good moments

## The problem this document solves

A naive activity measure rewards flailing and punishes a clean single-tempo thrust, and on
handheld footage it mostly measures the camera. Both failures were observed in the prototype.
Everything here exists to fix one or the other.

## Camera compensation (mandatory)

Camera shake in phone footage is comparable in magnitude to fighter motion. Any activity
signal MUST subtract global motion before it is used for ranking.

Baseline: `activity = motion_in − k · motion_out` with `k = 0.8`, where `motion_in` is mean
absolute frame difference inside the fighter boxes and `motion_out` is the same outside them.
`motion_out` is retained in the manifest so `k` can be revisited without re-decoding
(`002_manifests.md`).

Preferred, once available: estimate a per-frame homography from background feature matches
with the fighter boxes masked out, warp the previous frame onto the current one, and measure
dense optical flow inside the fighter masks on the compensated pair. Report both the **mean**
and the **95th percentile** of flow magnitude — the percentile captures blade and hand
velocity, which the mean averages away.

## Fighters

Person boxes taller than 22 % of frame height; the two tallest are the fighters. Bystanders
are small. Identity across sampled frames is kept by nearest-centre matching, with the pair
ordered left-to-right per frame and swapped only when the crossed assignment is cheaper.

`gap` is the horizontal distance between fighter centres minus their half-widths, divided by
mean fighter height. Normalising by height makes it invariant to pan and zoom. A gap below
0.7 means the fighters are in measure.

## The halt is the signal

In HEMA, after a touch both fighters stop and reset for the referee. That stop is far more
detectable than the hit itself, and it is what anchors a cut.

**Halt** = a fall in smoothed activity followed by at least 0.8 s that stays settled. The
candidate's `anchor` is the halt.

**Settled** is measured against the clip's own quiet-to-busy range — the 25th and 95th
percentiles of its activity — not against its median. A clip is mostly *not* fencing:
approach, reset, the referee talking. Its median therefore sits at the resting level, and
nothing can fall below it, so a median-based test finds no halts at all on exactly the
material this is for.

**Onset** = walking back from the halt, the last moment activity was still at rest. The clip
then opens on the approach rather than mid-exchange.

Window = `onset − 0.5 bar` … `halt + 0.3 s`, later snapped to a whole number of bars by the
director.

For `short` sources the halt is at the end by construction, so the baseline strategy — window
= last 4.5 s minus a 0.3 s tail — is permitted as a fallback when halt detection finds
nothing. For `long` sources halt detection is **required**; there is no "end of file" to lean
on.

## Kinematics: separating a thrust from flailing

Activity magnitude alone cannot tell a decisive action from an energetic one. The
discriminator is **closing speed**: the rate at which the target's leading hand or foot
approaches the opponent in the 300 ms before the halt.

- Large limb displacement **with** closing → a committed attack.
- Large limb displacement **without** closing → flailing, exchange of nothing, or a parry
  flurry.

Keypoints come from a pose model over the two fighter boxes. This is an optional backend
(`004_stack.md`); when it is absent, `closing_speed` is null and the composite score falls
back to the box-centre convergence rate, which is coarser but free.

## Material: fencing, or something else

`006_music.md` forbids fight material before the drums arrive, and `002_manifests.md` carries
a `material` field, so something has to decide which a window is.

**Motion cannot make this distinction.** A hug is vigorous. A salute can include a clash. Any
rule keyed on how much movement there is will call them fencing, and the reference footage
proved it: every window a motion-based rule called non-fight was simply fencing measured from
slightly further out.

What separates them is what the **distance between the fighters does over time**. Fencing
closes to hit and breaks to reset, repeatedly. An embrace comes together and stays. A salute
or a walk-on holds its distance. So:

> **action** = both fighters visible, in measure at some point, and the gap *swings* —
> crossing the measure threshold, or ranging widely.
>
> **non_action** = one person in frame, or the gap holds steady and never crosses into
> measure, however energetic the window looks.
>
> **unknown** = anything else.

`unknown` is a real verdict, not a placeholder. Fencing is a continuum and a window near the
thresholds is genuinely undecided; the director treats it as unconstrained and
`material_match` reports that it could not verify placement rather than passing
(`008_render.md`). A guess dressed as a classification is worse than an honest absence — it
puts a lunge under a quiet chord behind a green check.

`material` MUST also remain `unknown` when no classifier has run at all.

### Non-exchange windows must be proposed, not just recognised

A halt-anchored candidate stage proposes windows built around exchanges, so warm-ups, salutes,
walk-ons and hugs are never candidates in the first place — none of them produce a halt. The
drumless intro then has nothing honest to draw on however good the classifier is.

The stage MUST therefore also propose windows of two further kinds, both carrying
`origin: "calm"`:

- **stable-gap windows** — stretches where the distance between the fighters does not move;
- **solo windows** — stretches where exactly *one* fighter is on camera.

The second is not a special case of the first: measuring a gap needs two fighters, so a
one-person walk-on has no gap to hold steady and stable-gap detection can never find one.
"Exactly one" and not "at most one" — a stretch with nobody detected is a camera on the floor
or a failed detection, and the director prefers fewer fighters on camera, so counting empty
frames would open the reel on nothing.

The both-fighters-visible gate does not apply to `calm` windows: an exchange is worthless
without both fighters in frame, while a walk-on with one person is exactly what the intro
wants.

A `calm` window MUST be at least as long as the slot it is placed in. A clip is anchored at
its window end and reaches back the length of its slot; for an exchange that reach-back is the
approach and is wanted, but for a calm window it renders footage no classifier examined —
usually the tail of the exchange that preceded the stillness, which is how fight material
reaches the drumless intro behind a passing check.

## Composite score

`score` ∈ [0, 1], a weighted combination of:

| feature | direction | note |
|---|---|---|
| `peak_activity` | higher better | compensated |
| `closing_speed` | higher better | null-safe |
| `both_visible_frac` | higher better | fraction of window with two fighters detected |
| `min_gap` | lower better | were they ever in measure |
| `median_sharpness` | higher better | rejects motion-blurred and out-of-focus windows |

Weights live in configuration, not in code constants, because they are the thing the
benchmark tunes.

## Quality gates (hard drops, before scoring)

A window is dropped, with the reason recorded in `flags`, when:

- fewer than two fighters are visible in more than 30 % of the window;
- in `personal` mode, the target is absent or occluded for more than 30 % of the window;
- **the source cannot fill the shortest permitted slot** (see below);
- a scene cut or camera drop occurs inside it.

### The minimum-slot gate

A clip occupies a whole number of bars, so the shortest usable window is the shortest slot the
director may create — one bar, which only the reel's opening may be (`006_music.md`). A
candidate whose source cannot supply that much footage ending at its anchor is **not a
candidate at all** and MUST be dropped here, flagged `source_too_short`.

The gate is deliberately the *absolute* floor rather than the usual two-bar clip length: a
window that can only fill the opening is still usable, and the director decides per slot
whether a given candidate is long enough for it.

This gate is tempo-dependent and therefore evaluated after `music.json` exists. It is stated
as a scoring gate rather than left to the director because a window that can never be
rendered is not a weak candidate — it is not a candidate.

Stretching such a window instead is the defect this gate exists to prevent: reaching past the
end of a source produces frames that were never decoded, which appear as a freeze
(`008_render.md`).

## Visual review

Heuristics propose, vision disposes. The single most valuable step in the prototype was a
model looking at a 5-frame filmstrip of every candidate: it caught opponents out of frame,
cameras pointed at a fighter's back, spectators walking through, and dropped phones — none of
which any of the signals above notice.

The pipeline MUST therefore produce filmstrips for every candidate and MUST support an agent
verdict per candidate (`candidates.json.agent`). Whether that verdict comes from a VLM
backend or from the orchestrating agent reading the strips is an implementation choice; the
contract is the same. Expect to drop 30–40 % of candidates at this step.

## Target identification (personal mode)

1. Cluster the per-fighter kit features from `analysis/*.json` (median HSV of a jacket band
   and a trouser band) with k-means, k = 4–6. Lighting and shadow make this noisy; it is a
   first pass, not a verdict.
2. The cluster present in nearly every source is the target. When the user has said the
   target appears in every clip, this usually resolves it alone.
3. Otherwise show one cropped snapshot per cluster and ask for one click.
4. Within a candidate, the target is the tracked fighter whose kit feature is nearer the
   target centroid; record it as `target_side`.

Face recognition and person re-identification are out of scope: fighters are masked.

## Benchmark, not unit test

The handover bundle carries ground truth: 69 candidate windows, of which **16 have a user
verdict** — six keeps and ten drops. The verdicts are recorded as prose in the bundle's
`handover.md`, not as fields in its `candidates.json`, which holds the prototype's own features
and no verdict at all. The agent's judgement of the same windows survives only as which
thirteen reached the prototype's final EDL.

It ships as a test fixture holding each window's features **as this build measures them** —
scoring the prototype's recorded numbers would benchmark the prototype. The fixture is
therefore generated from an analysed project and regenerated when the analysis changes.

A `bench` target reports:

- **Separation** — over every keep/drop pair, how often the kept window scores higher. 1.0
  means every keep outranks every drop; 0.5 is a coin flip. Chosen over rank correlation
  because sixteen labelled points are too few for a correlation to mean anything.
- **Gate recall** — how many kept windows survive the quality gates. A keep dropped before
  scoring is a worse failure than one ranked badly, and the composite score cannot see it.
- **Top-of-reel recall** — how many kept windows reach the number of slots a reel actually
  holds.

This is a **reported metric with a regression floor**, not a pass/fail assertion on exact
ordering — a scorer that reproduces one person's taste exactly is overfitted, and an
equality assertion would make every legitimate improvement look like a failure. Sixteen labels
are far too few to fit the weight vector to; the benchmark exists to catch a regression and to
justify a weight change in writing, not to be optimised against.
