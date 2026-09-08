# 001 — Product Goal and Scope

## Goal

Turn amateur footage of a HEMA tournament into a short highlight reel cut to music, with a
human input budget of a few minutes rather than an evening in an NLE.

## Inputs

- **Footage**, either shape:
  - *clip-per-exchange*: many short files (typically ≤ 9 s), each ending shortly after the
    touché. This is what a phone-filming spectator produces.
  - *single long recording*: one file, minutes to hours (stream capture, fixed camera).
  A project MAY contain both shapes at once.
- **Music track** (optional). When absent, the reel is cut to a procedurally generated grid
  at a chosen BPM.
- **Steering** (all optional): output mode, target fighter description, duration, resolution,
  chronology hints.

## Output

- One MP4, 16:9, ~60 s by default.
- The `edl.json` that produced it. **The EDL is a first-class deliverable**, not a
  by-product: it is what makes a re-render reproducible and what the user edits when they
  want a different cut.

## Modes

| mode | meaning |
|---|---|
| `event` | best moments across the whole tournament, no single protagonist |
| `personal` | best moments of one fighter; every selected clip must contain them |

`personal` mode additionally runs the identity stage (see `005_scoring.md` §Target
identification) and biases scoring and framing toward the target.

## Human input budget

The pipeline MUST be able to produce a reel with **zero** human input beyond starting it.
Every interactive step is an override, never a requirement:

1. Target confirmation — one click, only in `personal` mode, only when identification is
   ambiguous.
2. Per-clip verdict — keep / drop / agent's call. Untouched candidates default to *agent's
   call*.
3. Optional trims, optional ordering hints, optional free-text notes to the agent.

## Out of scope, permanently

- No face recognition or person re-identification. Fighters wear masks; kit colour plus
  "present in every clip" is the signal that works (`005_scoring.md`).
- No cloud upload of footage. All processing is local (`004_stack.md`).
- Not a general video editor. The scope is this one shape of edit.

## Deferred

Wanted, not yet built. Listed here because each one constrains a decision being made now —
the point is to keep the door open, not to build behind it. Nothing in this section may be
implemented speculatively.

| capability | what it costs when it arrives |
|---|---|
| transitions (cross-fades, wipes) | the assembly stage stops being a stream copy — see `008_render.md` |
| slow motion | frame interpolation, **and** the clip-length arithmetic changes (`008_render.md`) |
| colour grading | a per-clip or per-project look field in the EDL; additive |
| titles and lower-thirds | an overlay track in the EDL; additive |

Manifests carry `schema_version` and JSON objects accept new keys, so grading and titles need
nothing reserved for them today: they arrive as new optional fields without a migration. Do
not pre-build an overlay system for them.

Transitions and slow motion are different — they invalidate assumptions the renderer relies
on right now, so those assumptions are marked as conditional where they are stated rather
than discovered later.

Until then the deliverable has hard cuts, a fade in and out, and `speed == 1.0`.

## Definition of a good reel

Used as the acceptance frame for the whole system; each item is made concrete in a later
document.

- Every cut lands on a bar line of the **fitted** music grid (`006_music.md`).
- The strongest action lands on the track's strongest structural moment.
- Non-fight material (salutes, walk-ons, hugs) appears only in a drumless intro or outro.
- No two consecutive clips from the same bout and angle, unless the second escalates.
- In `personal` mode, the target is visible in every clip.
- No visual artefacts: no brightness-jump flashes, no zoom pumping (`008_render.md`).
