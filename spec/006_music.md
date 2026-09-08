# 006 — Music analysis

Output is `music.json` (`002_manifests.md`). It is the timeline every cut is placed on.

## Grid

**Fit the period; never trust a reported tempo and never round it.** In the prototype the
tracker reported 117.45 BPM; assuming 120 drifted 0.7 s over a single minute — a full beat,
visible as every cut sliding off the music.

Baseline procedure:

1. Beat times from `librosa.beat.beat_track(units='time')`.
2. `beat_s` = median of the beat intervals. `bpm` = `60 / beat_s`, carried as a float.
3. `first_downbeat_s`: of the `beats_per_bar` candidate phases, take the one with the highest
   mean onset strength at bar starts.
4. `bar_s = beats_per_bar × beat_s`, with `beats_per_bar` defaulting to 4.

Optional backend: Beat This! gives beats and downbeats directly and needs no phase search.
When present it supplies `first_downbeat_s` and `beat_s`; the fitted-period rule still
applies to whatever beat list is returned.

## Sections

Structure is recoverable from three per-bar signals, all cheap:

- **low-band energy** (< 150 Hz) — drums and bass in or out;
- **high-band energy** — intensity;
- **chroma top-3** — harmonic movement.

Section boundaries are jumps in low-band energy and shifts in the chroma set;
`librosa.segment.agglomerative` over beat-synced MFCC + chroma cross-checks them. This
baseline recovered intro / drop / B-section / climax / outro cleanly from a 60 s stock track.

Optional backend: All-In-One returns boundaries **with functional labels**
(intro/verse/chorus/bridge/outro). When absent, sections are named positionally
(`intro`, `s1`, `s2`, …, `outro`) and MUST NOT be given invented functional names — a
positional label the director can reason about is honest; a guessed "chorus" is not.

All-In-One is optional rather than the default for a hard reason, not a preference: it
requires `natten` on macOS, which publishes no distribution for the platform and must be
compiled against a torch build environment, and it pulls `demucs` and the whole PyTorch tree
that `004_stack.md` deliberately keeps out of the base install. As a default it would make
environment setup fail outright on a supported machine — taking the video pipeline down with
it, for a music-labelling improvement.

The loss is bounded: the director's rules key off energy and low-band content, not off
section names (see the mapping rules below), so labels improve legibility more than output.

## Chords

`chord_change_bars` lists the bar indices where harmony moves. Baseline: change in the top-k
chroma set between consecutive bars. Optional backend: a chord recogniser (Chordino, BTC)
for actual labels.

This exists so the director may cut mid-section on a harmonic change when a clip needs an odd
number of bars — not so that cuts float freely to chord onsets. **Cuts land on bar lines.**

## Mood

Per **section**, never per track: sections differ, and the per-section vector is what clips
are matched against.

Baseline: `energy` from RMS. No mood tags — the baseline MUST leave `arousal`, `valence` and
`mood_tags` null rather than fabricate them.

Optional backend: Essentia mood/theme tags plus arousal–valence regressors; CLAP for
open-vocabulary descriptors when the fixed tag set is too coarse.

## Procedural fallback

With no track, generate one at a chosen BPM. `music.json` is filled from the generator's own
parameters, so the grid is exact by construction and `source` is `"procedural"`. This is a
usable placeholder for testing the whole pipeline without a licensed track; it is not a
substitute for one in a delivered reel.

## Mapping rules for the director

These are the rules that worked, recorded here because they are musical judgements rather
than derivable facts:

- Drumless intro → non-fight material: warm-ups, walk-ons, salutes, hugs. It is the only
  place that material works.
- The drop (drums in) → the single most explosive clip.
- A harmonic shift → start a new run of clips.
- The densest bars → the finale.
- Outro (drums out) → one coda clip with a video fade, never the finale.
- Within a section, order for build; land the highest-scoring clip's halt on the section's
  first downbeat.
- Match section arousal to clip peak activity: high-arousal sections get the explosive
  material, low-arousal sections get the calm material.
