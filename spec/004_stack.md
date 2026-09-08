# 004 — Stack and runtime

## Runtime

**The project runs directly on the host.** No container, in development or in use. Rationale:
it is a local media tool operating on local files, the heavy dependency (`ffmpeg`) is a
system package either way, and optional accelerated backends (`006_music.md`,
`005_scoring.md`) need direct access to the machine's GPU. The isolation a container would
buy is not worth the media-mount and device-passthrough friction.

Consequence: reproducibility rests on declared dependency floors plus `agent-make doctor`,
not on an image. `doctor` MUST verify every host prerequisite and fail with an actionable
message naming the fix.

## Host prerequisites

| tool | required for | check |
|---|---|---|
| Python ≥ 3.12 | everything | version |
| `ffmpeg` with `libvidstab` | render, proxies | `ffmpeg -filters` lists `vidstabtransform` |
| `ffprobe` | ingest | presence |

`libvidstab` is not a given: Homebrew's `ffmpeg` formula omits it and only `ffmpeg-full`
carries it, keg-only. A `doctor` failure MUST therefore name the formula and the PATH change,
not merely say "install ffmpeg" — the obvious install produces an ffmpeg that fails at the
render stage, minutes of analysis later.

Tests that need `ffmpeg` MUST skip cleanly when it is absent, so the unit suite still runs on
a bare machine.

## Python dependencies

Runtime:

| package | role |
|---|---|
| `numpy`, `scipy` | signal work |
| `opencv-python` | decode, detection pre/post-processing, optical flow |
| `librosa`, `soundfile` | music baseline: beat tracking, chroma, band energies |
| `onnxruntime` | person detection (YOLOv8n ONNX, CPU, no torch) |
| `pydantic` ≥ 2 | manifest schemas — the single source of truth for `002_manifests.md` |
| `typer` | CLI |
| `fastapi`, `uvicorn`, `jinja2` | review server |
| `pillow` | filmstrip contact sheets |

Dev: `pytest`, `pytest-cov`, `httpx` (ASGI test client), `ruff`.

**PyTorch is not a runtime dependency.** Detection runs through ONNX Runtime on CPU. Anything
that needs torch belongs behind an optional backend (below).

## Model assets

Weights are not in the repository: they are large, and not ours to redistribute. They live in
a gitignored `models/` and are fetched on demand by `hlreel fetch-models`, which is the **only
command that reaches the network**.

Each asset is pinned by SHA-256 and lands on a temp name before being renamed into place, so
an interrupted download cannot leave a truncated file that later looks present. `doctor`
reports a missing or mismatched asset as a prerequisite failure — a stage discovering it
minutes into an analysis run is a worse way to find out.

Being honest about what the pin buys: the digest was recorded from the first download rather
than published by an authority. It protects against the file changing at its source, not
against it having been wrong to begin with. Anyone re-pointing an asset at a new URL should
treat the first fetch as the trust decision.

| asset | used by | source |
|---|---|---|
| `yolov8n.onnx` | person detection (`005_scoring.md`) | the ONNX export the reference prototype ran on, so rankings stay comparable across it |

## Manifest schemas

Every manifest in `002_manifests.md` MUST have a corresponding pydantic model. The models are
authoritative: the CLI validates on read and on write, and the review UI is served the JSON
Schema generated from them rather than a hand-maintained copy.

## Optional backends

Quality-improving components that need heavy or GPU dependencies are **pluggable and
detected at runtime**. Each has a deterministic CPU baseline that is always present. A
manifest records which backend produced each field (`music.json.backends`), so a result can
be traced.

| slot | baseline (always) | optional |
|---|---|---|
| beat/bar grid | `librosa` beat track + period fit | Beat This! (ONNX) |
| music sections | band-energy + chroma segmentation | All-In-One (`allin1`) |
| mood | none | Essentia mood/arousal-valence heads, CLAP |
| fighter kinematics | box-centre convergence rate | pose keypoints (RTMPose/ViTPose, YOLOv8-pose) |
| candidate re-rank | composite score | VLM filmstrip scorer, Lighthouse |

Installing an optional backend MUST NOT change the baseline's output. The test suite
exercises baselines and fakes only; backends are covered by a benchmark target, not by unit
tests.

## No database

The project directory is the store (`002_manifests.md`). No ORM, no migrations, no alembic.
Concurrency is single-writer per project; the CLI takes a lock file on the project directory
for the duration of a stage.

## Web layer

FastAPI with Jinja2 templates and hand-written JavaScript — **no frontend build step**. The
review UI is a few hundred lines of DOM code; a bundler would add a toolchain to a project
whose real dependencies are ffmpeg and numpy. Static assets are served from the package.

The server binds to loopback by default and serves media only from within the project
directory it was started for.

## Repository layout

```
app/
  manifests/     pydantic models, one module per manifest
  stages/        ingest, analyze, candidates, identity, music, proxies, director, render
  video/         decode, detection, flow, crop, ffmpeg wrappers
  audio/         grid fitting, sections, backends
  web/           FastAPI app, templates, static — this is the `review` stage
  host.py        host prerequisite checks
  cli.py         typer entry point
tests/unit/      pure functions, synthetic fixtures
tests/it/        stage-to-stage flows, ASGI client
```
