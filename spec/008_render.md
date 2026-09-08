# 008 — Render

Render is a deterministic function of `edl.json`, the source files and the track. It reads no
other manifest (`003_pipeline.md`).

## Timing: cumulative, never per-clip

Frame counts MUST be computed cumulatively:

```
frames_for_clip_i = round(cumulative_bars_after_i × bar_s × fps)
                  − round(cumulative_bars_before_i × bar_s × fps)
```

Rounding each clip's length independently accumulates error and slides later cuts off the
grid. The video is offset by `first_downbeat_s` so the first cut lands on the first downbeat.

A clip's `out` is its candidate window end — the halt plus the short tail that lets the
action settle (`005_scoring.md`) — and `in = out − bars × bar_s`. When the
source is too short to reach back that far, the anchor moves later rather than the clip being
shortened — a clip that is not a whole number of bars breaks the grid for everything after
it.

That last identity holds only at `speed == 1.0`. A clip played at speed `s` consumes
`bars × bar_s × s` source seconds to fill the same slot, so `in = out − bars × bar_s × s`.
Slow motion is deferred (`001_goal.md`), and `speed` is fixed at `1.0` until it arrives —
but the arithmetic is written in its general form here so the factor is not mistaken for
redundancy and dropped.

## Decode

Decode **sequentially** from the clip's start. Per-frame seeking is an order of magnitude
slower and is not permitted in the frame loop.

Source frame rates vary (24 and 30 are both normal); frames are duplicated or dropped to
reach the output rate.

**The renderer MUST NOT emit a frame it did not decode.** Running past the end of a source is
a hard error naming the clip, never a repeated final frame: a repeat is invisible to the
encoder and to every downstream check, but a viewer sees the picture stop dead. The director
is responsible for never scheduling a slot longer than its source can fill
(`005_scoring.md`), so reaching this error means an upstream invariant broke and the fix
belongs there, not in a renderer fallback.

Frame duplication for frame-rate conversion is a different thing and stays: it repeats a
frame the renderer *has* decoded, to fill a 24 → 30 fps gap.

**Never crop a frame that has already been cropped.** The frame-duplication path must copy
from the retained source frame, not from the previously emitted output frame. Cropping an
already-cropped-and-upscaled frame produced a visible zoom flash every fifth frame on 24 fps
sources in the prototype; this is the invariant that prevents it.

## Framing

Tracked crop, from the union box of the two fighters:

- padding 1.45× horizontally, 1.25× vertically, forced to the output aspect;
- **one crop size for the whole clip** (the maximum required over the clip) — a per-frame
  size pumps the zoom;
- centre trajectory Gaussian-smoothed (σ ≈ 2 samples);
- zoom capped at **1.35×** for handheld ~720p sources, and up to **1.8×** for static
  high-resolution captures, where the crop is what makes the shot watchable.

On phone footage the fighters usually fill the frame and the cap binds on most clips; the
crop earns its keep on wide static shots. Resize with Lanczos.

Upscaling 720p sources to 1080p output is an upscale and MUST be reported to the user rather
than presented as a resolution gain. Tighter crops cost sharpness.

## Stabilisation

After the crop, not before (`003_pipeline.md`):

`vidstabdetect shakiness=5 accuracy=15` → `vidstabtransform smoothing=10 zoom=2 optzoom=0`
→ `unsharp=3:3:0.4`.

Heavier smoothing crops the fighters out of frame. These values are a ceiling, not a starting
point for tuning upward.

## Assembly

Concat the rendered clips, mux the track, fade video and audio over the outro, write with
`+faststart`. Intermediate clips are encoded at high quality (crf ≈ 12) so the concat stage
is the only place quality is spent.

Concatenation is a **stream copy** (`-f concat -c copy`), which is what keeps the assembly
stage nearly free. That is conditional on every boundary being a hard cut: a cross-fade spans
two clips and needs a filter graph over both, so it cannot be a copy. Transitions are deferred
(`001_goal.md`), and when they arrive the copy path stays for the cut-only case rather than
being replaced wholesale — most boundaries will still be cuts, and re-encoding all of them to
support a few would cost quality everywhere for a gain in two places.

Treat the copy as an optimisation guarded by a property of the EDL, not as the definition of
assembly.

## Automated QA

`render/qa.json` (`002_manifests.md`). Every check runs before the reel is presented:

| check | rule | status on violation |
|---|---|---|
| `brightness_jump` | no frame whose mean brightness departs from **both** neighbours by > 12 in the same direction | `fail` — this is the crop-flash signature |
| `frozen_tail` | no run of identical frames at a clip's end | `fail` — the source ran out |
| `grid_alignment` | every cut within one frame of a bar line | `fail` |
| `section_straddle` | no clip spans a `major` section boundary | `fail` |
| `material_match` | the track's low-energy opening got non-fight material | `warn` |
| `fade_target` | names the clip the outro fade lands on | `warn` if it is a fight clip |
| `duplicate_footage` | per-source 16×9 grey signatures compared across sources | `warn` |
| `target_present` | personal mode: target detected in every clip | `warn` |
| `consecutive_setup` | no two adjacent clips from the same source | `warn` |
| `duration` | within one bar of the requested length | `warn` |

A `fail` blocks presenting the reel as finished. The agent MUST report warnings rather than
suppress them.

`brightness_jump` tests for a spike, not for any large change. The artifact it exists to catch
is a frame that jumps and reverts; a camera panning into the sky moves as far in one frame and
stays there. Flagging every large frame-to-frame delta fails ordinary footage and trains the
reader to ignore the check.

`consecutive_setup` approximates the acceptance criterion in `001_goal.md`, which forbids
adjacent clips from the same bout and angle *unless the second escalates*. Source identity is
the machine-checkable half; escalation is a director's judgement. That is why the check warns
instead of failing — a warning the director can knowingly accept.

## Reproducibility

Re-rendering the same `edl.json` against the same sources MUST produce the same edit
decisions — identical cut points, identical crop rectangles. Encoder output need not be
bit-identical.
