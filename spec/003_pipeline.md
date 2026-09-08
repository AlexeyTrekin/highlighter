# 003 — Pipeline: stages, ordering, idempotency

## Stage graph

```
ingest ──> analyze ──┬──> candidates ──┬──> proxies ──> review ──┐
                     │                 │                          │
                     └──> identity ────┘                          ├──> director ──> render
                                                                  │
music ────────────────────────────────────────────────────────────┘
```

- `music` is independent of every video stage and MAY run in parallel with them.
- `identity` runs only in `personal` mode; it consumes the kit features already in
  `analysis/*.json` and never re-decodes video.
- `review` is **optional**. `director` MUST produce an EDL whether or not `review.json`
  exists.

## Why music precedes review

The bar length determines how long each clip will be, so it determines what the user is
shown and what a manual trim means. Running music analysis after review would silently
re-quantise every trim the user made. `director` MUST fail rather than run without
`music.json`.

## Why stabilisation is not a stage

Stabilisation is a render-time operation applied **after** the tracked crop
(`008_render.md`). Two reasons it MUST NOT be a pre-pass over the sources:

1. It would stabilise hours of footage that is then discarded, and add a full generation of
   re-encoding loss to material that is already phone-grade.
2. Analysis does not want stabilised pixels; it wants the **camera motion as a signal** so it
   can be subtracted from the activity measure (`005_scoring.md`). Removing camera motion
   from the pixels destroys the very quantity the compensation needs.

## Stage contracts

| stage | reads | writes | may re-decode video |
|---|---|---|---|
| `ingest` | input paths | `project.json` | probe only |
| `analyze` | source files | `analysis/vNN.json` | yes |
| `candidates` | `analysis/*` | `candidates.json` | no |
| `identity` | `analysis/*`, `candidates.json` | `identity.json`, snapshots | frame grabs only |
| `music` | track or nothing | `music.json` | n/a |
| `proxies` | source files, `candidates.json` | `proxies/`, `strips/` | yes |
| `review` | `candidates.json` | `review.json` | no (serves files) |
| `director` | `candidates.json`, `music.json`, `review.json?`, `identity.json?` | `edl.json` | no |
| `render` | `edl.json`, source files, track | `render/`, `highlight_vN.mp4` | yes |

A stage MUST NOT write outside the manifests listed for it. `analyze` is the only stage that
performs a full decode of every source, and it MUST be able to run per-source so work shards
cleanly across processes.

## Idempotency and resumability

- Every stage is **resumable at the unit of its output file**: `analyze` skips a source whose
  `analysis/vNN.json` exists, `render` skips a clip whose rendered file already holds every
  frame its slot needs. Existence alone is not enough: an interrupted encode leaves a
  non-empty but short file, and a short clip drags every later cut off the beat while every
  other check stays green.
- A stage MUST record `status` in `project.json.stages` before and after running, so an
  interrupted run is visible rather than being mistaken for a completed one.
- Re-running a completed stage without `--force` is a no-op that exits successfully.
- `--force` re-runs the stage and invalidates nothing downstream automatically; the CLI MUST
  warn when a downstream manifest is older than the one just rewritten.

## Long-recording path

For a source with `shape == "long"`, `candidates` uses a different strategy but the same
output contract:

1. Coarse pre-pass at ~1 fps, 320 px, detector-free: frame-difference energy and scene-cut
   detection. Purpose is to skip the minutes of setup and judging between bouts.
2. The detector runs only inside active regions, at ~5 fps.
3. Exchanges are found by halt detection on the continuous signal, not by "the clip ends
   here" (`005_scoring.md`).
4. Bout segmentation: gaps > 60 s with no fighters separate bouts. Opponent kit changes
   between bouts, so identity clustering runs per bout.
5. Chronology is trustworthy here (single timeline) and MAY be used for ordering. For
   clip-per-exchange input it is not: files that passed through a messenger carry the upload
   time as `creation_time`. The pipeline MUST NOT infer chronology from file metadata for
   `short` sources — it asks or leaves the order to the director.

## Failure policy

- A stage that cannot process one unit (a corrupt source, a candidate whose window falls
  outside the file) MUST record the failure against that unit and continue with the rest.
- A stage that cannot satisfy its contract at all (no music grid, no candidates) MUST fail
  loudly and leave the previous manifest untouched.
