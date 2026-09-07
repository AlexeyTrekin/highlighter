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

**Halt** = the largest negative derivative of smoothed activity that is followed by at least
0.8 s below the clip's baseline. The candidate's `anchor` is the halt.

**Onset** = the last point before the halt where activity rose above twice the rolling median.

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
- the window is shorter than 2 s;
- a scene cut or camera drop occurs inside it.

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

The handover bundle carries ground truth: 69 candidate windows with both agent and user
verdicts. It ships as a test fixture, and a `bench` target reports the rank agreement between
a scorer and the user's keep/drop decisions.

This is a **reported metric with a regression floor**, not a pass/fail assertion on exact
ordering — a scorer that reproduces one person's taste exactly is overfitted, and an
equality assertion would make every legitimate improvement look like a failure.
