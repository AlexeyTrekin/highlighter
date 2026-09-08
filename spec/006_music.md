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
`librosa.segment.agglomerative` over beat-synced MFCC + chroma cross-checks them.

### Detection is hierarchical

A single threshold finds only the loudest transition. On the reference track the sub-150 Hz
band steps ×1.7 at bar 1 as subtle drums enter and ×43 at bar 6 as the kit arrives; any
threshold that catches the second is deaf to the first, and a listener hears both.

Boundaries MUST therefore be detected at more than one sensitivity and **all of them kept**,
each tagged with a `level`:

| level | meaning | consequence for the cut |
|---|---|---|
| `major` | the music changes character — drums in or out, a new part | mandatory cut point |
| `minor` | a step within a part — band-energy change, chord change | preferred cut point |

Suppressing a minor boundary because a major one is nearby loses exactly the structure the
director needs to place a clip well.

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

## Where cuts may fall

Every cut lands on a bar line. Not every bar line is an equally good cut, and the director
MUST rank them:

1. **`major` section boundary** — mandatory. No clip may straddle one.
2. **`minor` boundary** — preferred. Use one when a clip needs an odd length, or when a
   section is long enough to hold several clips.
3. **plain bar line** — last resort, for when neither of the above lands where a clip must
   end.

A section short enough to be filled by one clip is filled by one clip. Splitting it at a bar
that carries no musical event produces a cut the listener hears as arbitrary, because it is:
the reference reel cut at bar 3 of a six-bar intro, where nothing happens in the music, and
the two acceptable endings a listener named were the two real boundaries at bars 1 and 6.

### The opening may be one bar

A clip is normally at least two bars. The reel's **first** slot is exempt and may be a single
bar.

Without the exception, a section whose first musical step falls one bar in can never be cut
there — the split would orphan a piece below the minimum — and the cut falls back to a plain
bar, which is the option ranked last above. On the reference track that step is at bar 1, one
of the two endings a listener actually named.

A one-bar opening is about two seconds, which is short for a shot. It is a default, not a
conviction: the correction stage MUST let a viewer merge it into the clip that follows
(`007_review_ui.md`). No other slot may be shorter than two bars, because a short clip
mid-reel reads as a mistake rather than an opening gesture.

## A section holds one kind of material

Material type MUST match section character, and this is checked rather than hoped for
(`008_render.md` `material_match`).

Concretely: **no fight clip is scheduled before the drums arrive.** The drumless intro is for
warm-ups, walk-ons, salutes and hugs, and an action clip placed there reads as a mistake even
when it lands exactly on a bar line.

Where material is known, prefer it over material nothing could classify: `unknown` winning a
quiet slot on score is how a lunge ends up under a still chord.

Within the intro and the coda, order candidates by **how unlike an exchange they are**, not by
score. The composite score ranks fencing quality, and using it here picks the most watchable
of the calm clips — which on real footage means fencing at long measure, since holding a
distance is precisely what makes a window read as calm. Fewest fighters on camera is the
strongest available evidence that nothing is being fought.

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
