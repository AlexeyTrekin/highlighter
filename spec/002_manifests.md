# 002 — Manifests: the data contract

The project directory **is** the state. There is no database. Every stage reads manifests and
writes manifests; the video is a deterministic render of `edl.json`.

## Project layout

```
<project>/
  project.json          project identity, options, per-stage status
  analysis/vNN.json     per-sampled-frame features
  candidates.json       candidate windows with scores and verdicts
  identity.json         kit clusters and target assignment   (personal mode)
  music.json            grid, sections, chords, mood
  proxies/cNNN.mp4      360p review previews, one per candidate
  strips/cNNN.jpg       filmstrip contact sheets
  review.json           human verdicts, trims, ordering hints
  edl.json              THE CONTRACT
  render/
    cNNN_<digest>.mp4   rendered clips
    qa.json             automated quality checks
  highlight_vN.mp4      deliverable
```

**Sources are referenced, not copied.** `project.sources[].path` is an absolute path to the
user's own file. Copying tens of gigabytes of footage into every project to gain a stable
`sources/vNN.mp4` is a poor trade for a local tool; the cost is that moving or deleting the
footage breaks the project, and `ingest` is where that would be detected.

A rendered clip's filename carries a digest of everything affecting its pixels, so a re-cut
EDL cannot silently reuse the previous cut's clip at the same slot.

The deliverable is **versioned and never overwritten**: comparing a new cut against the last
one is how an edit gets judged.

## Universal rules

- All manifests are UTF-8 JSON objects with a top-level `schema_version` (integer, starts at
  `1`) and `stage` (the stage name that produced it).
- **All times are seconds as floats**, measured from the start of the file they refer to.
  Never frame indices, never milliseconds. Frame counts appear only inside the renderer.
- **All boxes are `[x1, y1, x2, y2]` in source-frame pixels**, origin top-left.
- Identifiers: sources are `vNN` (`v01`…), candidates are `cNNN` (`c001`…). Both are stable
  for the life of a project — a re-run of a stage MUST NOT renumber existing entries.
- A stage MUST write its manifest atomically (temp file + rename) so an interrupted run
  never leaves a half-parsed manifest behind.

## `project.json`

| field | type | meaning |
|---|---|---|
| `id` | str | project directory name |
| `created_at` | str | ISO-8601 |
| `mode` | `"event"` \| `"personal"` | see `001_goal.md` |
| `target_hint` | str \| null | free-text kit description, e.g. `"black jacket, white trousers"` |
| `options` | object | `duration_s`, `width`, `height`, `fps`, `max_candidates`, `weights` |
| `music_path` | str \| null | absolute path to the track; null means procedural |
| `sources` | array | one record per input file |
| `stages` | object | stage name → `{status, started_at, finished_at, error}` |

`max_candidates` bounds how many windows are **presented for review** (`007_review_ui.md`),
not how many are generated. Capping generation would decide which footage is even considered
by file order, which is arbitrary; the candidate stage examines every source and ranking
decides what a human sees.

`sources[]` record: `id` (`vNN`), `original_name`, `path`, `duration_s`, `fps`, `width`,
`height`, `shape` (`"short"` | `"long"`), `signature`.

`signature` is a coarse greyscale thumbnail of a mid-file frame, flattened. It exists so
`duplicate_footage` (`008_render.md`) can tell that two sources are the same recording
uploaded twice — a real hazard when clips arrive through a messenger.

`shape` is decided at ingest from duration and MUST be recorded, because it selects the
candidate-generation strategy (`003_pipeline.md`).

`stages[].status` ∈ `pending` | `running` | `done` | `failed`.

> The prototype kept a separate `name_map.json`. Original filenames live in
> `sources[].original_name` instead: one manifest, one source of truth.

## `analysis/vNN.json`

Produced per source. `rows` is one entry per **sampled** frame (not per frame).

Top level: `source_id`, `fps`, `frame_count`, `width`, `height`, `duration_s`,
`sample_step` (every Nth frame), `rows`.

`rows[]`:

| field | type | meaning |
|---|---|---|
| `t` | float | timestamp in the source |
| `boxes` | array | 0–2 fighter boxes, ordered left-to-right, identity-tracked across rows |
| `kits` | array | per box, `[h_top, s_top, v_top, h_bot, s_bot, v_bot]` median HSV, or null |
| `motion_in` | float | motion energy inside fighter boxes |
| `motion_out` | float | motion energy outside fighter boxes (camera proxy) |
| `activity` | float | camera-compensated activity — see `005_scoring.md` |
| `gap` | float \| null | inter-fighter gap normalised by mean fighter height |
| `sharpness` | float | Laplacian variance |
| `brightness` | float | mean luma |

`motion_out` MUST be retained even when `activity` is present: it is what lets a later stage
recompute the compensation with a different coefficient without re-decoding the video.

## `candidates.json`

`{schema_version, stage, candidates: [...]}`. The windows live under a key rather than at the
top level so the manifest can carry the universal fields like every other one.

`candidates[]`:

| field | type | meaning |
|---|---|---|
| `id` | str | `cNNN` |
| `source_id` | str | `vNN` |
| `start`, `end` | float | window bounds in source seconds |
| `anchor` | float | the moment the cut is built around — the halt (`005_scoring.md`) |
| `kind` | `"short"` \| `"long"` | which strategy produced it |
| `origin` | `"halt"` \| `"fallback"` \| `"calm"` | how the window was proposed; the gates differ by origin (`005_scoring.md`) |
| `material` | `"action"` \| `"non_action"` \| `"unknown"` | what the clip contains, which decides where in the music it may sit (`006_music.md`) |
| `features` | object | `peak_activity`, `median_sharpness`, `both_visible_frac`, `min_gap`, `closing_speed`, `gap_variation`, `measure_crossings` |
| `score` | float | composite interestingness, 0–1 |
| `agent` | object \| null | `{verdict, reason, confidence}` from the visual/VLM reviewer |
| `target_side` | `"L"` \| `"R"` \| null | which tracked fighter is the target (personal mode) |
| `flags` | array of str | e.g. `"opponent_out_of_frame"`, `"occluded"`, `"camera_drop"` |

`agent.verdict` ∈ `keep` | `drop` | `unsure`. A dropped candidate stays in the file with its
reason; nothing is deleted, so a decision can always be audited or reversed.

`material` defaults to `unknown` and MUST stay `unknown` until something actually classifies
the clip. The director treats `unknown` as unconstrained rather than assuming either way, and
the `material_match` check (`008_render.md`) reports that it could not verify placement —
guessing here would put a fight clip in a drumless intro under a green check.

`start` and `end` are clamped to the source's duration by the gating stage, so no later stage
has to defend against a window that reaches past the end of its file.

## `identity.json` (personal mode only)

`clusters[]`: `{id, centroid, member_count, present_in_sources, snapshot}` where `snapshot` is
a path to a cropped peak frame used for the confirmation UI.
`target_cluster_id`, `confirmed_by` (`"user"` | `"heuristic"`),
`assignments`: candidate id → `{side, confidence}`.

## `music.json`

| field | type | meaning |
|---|---|---|
| `source` | `"track"` \| `"procedural"` | |
| `path` | str \| null | |
| `duration_s` | float | |
| `grid` | object | `bpm`, `beat_s`, `bar_s`, `first_downbeat_s`, `beats_per_bar` |
| `sections[]` | array | `{name, level, bar_start, bar_end, energy, arousal, valence, mood_tags[]}` |
| `chord_change_bars` | array of int | bar indices where harmony shifts |
| `bars[]` | array | per-bar `{index, t, rms, low_energy, high_energy, chroma_top[]}` |
| `backends` | object | which analyser produced each field, for reproducibility |

`grid.bpm` is the **fitted** tempo, not a reported or rounded one (`006_music.md`).

`sections[].level` is `major` or `minor` (`006_music.md`). Both are present in the same list:
a minor boundary inside a major section is a section in its own right, so the director can
treat it as a permitted cut point without losing the enclosing structure.

## `review.json`

| field | type | meaning |
|---|---|---|
| `verdicts` | object | candidate id → `"keep"` \| `"drop"` \| `"agent"` |
| `trims` | object | candidate id → `{start, end}` overriding the candidate window |
| `order` | object | `{mode: "auto"\|"strict"\|"weighted", sequence[], opening[], ending[], weights{}}` |
| `notes` | object | candidate id → free-text note for the agent |
| `completed` | bool | user pressed done; absent or false means the agent may proceed anyway |
| `updated_at` | str | ISO-8601, bumped on every autosave |

A candidate with no entry in `verdicts` is treated as `"agent"`. This is what makes the
review step genuinely optional.

## `edl.json` — the contract

```json
{
  "schema_version": 1,
  "stage": "director",
  "grid": {"bpm": 117.45, "beat_s": 0.5109, "bar_s": 2.0435,
           "first_downbeat_s": 0.232, "beats_per_bar": 4},
  "music_sections": [{"name": "intro", "level": "major", "bar_start": 0, "bar_end": 5,
                      "energy": 0.13, "mood_tags": ["calm"]}],
  "output": {"width": 1920, "height": 1080, "fps": 30, "duration_s": 61.3},
  "clips": [
    {"candidate_id": "c067", "source_id": "v49",
     "in": 1.37, "out": 5.46,
     "bars": 2, "grid_slot": 6, "section": "s1",
     "crop": {"mode": "tracked", "zoom": 1.0},
     "speed": 1.0, "stabilize": true, "material": "action",
     "target_side": "L", "score": 0.83,
     "order_reason": "highest score in section s1; lands its halt on the downbeat",
     "why": "lunge, both visible, drop-landing"}
  ]
}
```

- `in`/`out` are source seconds. `out − in` MUST equal `bars × grid.bar_s` within one output
  frame.
- `grid_slot` is the bar index at which the clip starts on the music timeline. Slots MUST be
  contiguous and non-overlapping.
- `crop.mode` ∈ `"none"` | `"tracked"` | `"fixed"`; a `"fixed"` crop carries an explicit
  `{x, y, w, h}`.
- `speed` is reserved (always `1.0` — slow motion is deferred, `001_goal.md`) and MUST be accepted by
  the renderer so the field can be used without a schema change.
- `music_sections` carries the same `Section` shape as `music.json`, copied verbatim, so the
  EDL stays self-contained without introducing a second spelling of the same thing. Checks
  that judge placement read it from here rather than from `music.json`: a hand-set EDL may not
  match the project's current music analysis, and judging it against sections it was never
  built from reports a fault that is not there.
- `material` is copied from the candidate for the same reason — placement checks must not have
  to reach back into `candidates.json`.
- `why` is a human-readable justification of the clip. It exists so the user can argue with
  the edit.
- `order_reason` justifies the clip's **position**, which is a separate question from whether
  the clip is good.

An EDL is **self-contained enough to re-render** given the source files: no stage downstream
of the director may consult `candidates.json` or `review.json`.

### The director is deterministic

The same inputs MUST produce a byte-identical `edl.json`. Ordering that depends on set
iteration, dictionary insertion, timestamps or unseeded randomness is a defect, not a
detail: when clips move between runs the user cannot tell an improvement from drift, and a
position they were happy with silently disappears.

Together with `order_reason`, this makes every position accountable — it either follows from
an input the user can see, or it is a bug. Positions the user pinned
(`review.json.order`) are never overridden; the director places only what was left to it.

## `render/qa.json`

`checks[]` of `{name, target, status, detail}` with `status` ∈ `pass` | `warn` | `fail`,
plus a top-level `status`. Checks are defined in `008_render.md`.
