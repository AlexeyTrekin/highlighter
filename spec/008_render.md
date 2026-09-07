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

## Decode

Decode **sequentially** from the clip's start. Per-frame seeking is an order of magnitude
slower and is not permitted in the frame loop.

Source frame rates vary (24 and 30 are both normal); frames are duplicated or dropped to
reach the output rate.

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

## Automated QA

`render/qa.json` (`002_manifests.md`). Every check runs before the reel is presented:

| check | rule | status on violation |
|---|---|---|
| `brightness_jump` | no `\|Δ mean brightness\| > 12` between consecutive frames | `fail` — this is the crop-flash signature |
| `grid_alignment` | every cut within one frame of a bar line | `fail` |
| `duplicate_footage` | per-source 16×9 grey signatures compared across sources | `warn` |
| `target_present` | personal mode: target detected in every clip | `warn` |
| `consecutive_setup` | no two adjacent clips from the same source | `warn` |
| `duration` | within one bar of the requested length | `warn` |

A `fail` blocks presenting the reel as finished. The agent MUST report warnings rather than
suppress them.

`consecutive_setup` approximates the acceptance criterion in `001_goal.md`, which forbids
adjacent clips from the same bout and angle *unless the second escalates*. Source identity is
the machine-checkable half; escalation is a director's judgement. That is why the check warns
instead of failing — a warning the director can knowingly accept.

## Reproducibility

Re-rendering the same `edl.json` against the same sources MUST produce the same edit
decisions — identical cut points, identical crop rectangles. Encoder output need not be
bit-identical.
