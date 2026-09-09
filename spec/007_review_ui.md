# 007 — Review UI

## Why a local server and not a chat-hosted page

The review surface needs real video playback with seeking over dozens of clips. A page hosted
outside the machine cannot reach local files, and the footage is far too large to upload. So
the UI is served by a local process from the project directory, and the agent's contribution
is a URL plus, afterwards, reading `review.json` back.

The server binds to loopback and serves media only from within the project directory it was
started for.

## Principles

- **The UI is an override, never a gate.** Everything works untouched: an unvisited project
  renders with every candidate on *agent's call*.
- **Nothing is lost.** Every interaction autosaves to `review.json`. Closing the tab mid-way
  is a supported way to stop.
- **Triage speed over completeness.** The common action is a single keystroke per clip.

## Views

### 1. Target confirmation (personal mode, only when ambiguous)

One cropped snapshot per kit cluster, with how many sources it appears in. One click writes
`identity.json.target_cluster_id` and `confirmed_by = "user"`.

### 2. Candidate review

A grid of cards. Each card carries: a looping 360p proxy, the candidate id and source, the
duration, the score, and the agent's verdict with its one-line reason.

Verdict control — three states, matching the user's own vocabulary:

| state | meaning | key |
|---|---|---|
| **Drop** | irrelevant, never use | `1` |
| **Agent's call** | average, decide for me | `2` (default) |
| **Keep** | best, must appear | `3` |

`J`/`K` move between cards. Candidates the pipeline already hard-dropped
(`005_scoring.md` quality gates) are collapsed into a "dropped" section with their reasons,
expandable so the user can rescue one.

### 3. Trim

Per card, a dual-handle range over the source window with a scrub preview. The handles show
where the bar-snapped result will land, so the user sees the cut they will actually get
rather than the window they dragged. Writes `review.json.trims`.

**A trim binds.** Nothing downstream may render outside it. A clip is normally anchored at its
window end and reaches back the length of its slot — for a detected exchange that reach-back is
the approach and is wanted, but a trim is a statement about which seconds to use, and reaching
past its start puts back the footage the user just removed. A trim too short for any slot
therefore makes the clip unusable, which is reported rather than silently applied.

## When the pipeline cannot do what was asked

A **keep** that does not reach the reel MUST be reported with the reason — trimmed below the
shortest slot, dropped by a gate, or beaten to the last slot. A keep is the strongest signal
the pipeline gets; one that quietly fails to appear is the worst outcome available, because a
decision was made, the reel ignored it, and nothing said so.

### 4. Ordering

Optional and skippable. Three modes:

- `auto` — the director decides. Default.
- `strict` — the user drags kept clips into an explicit sequence.
- `weighted` — the user gives clips a position weight and fills **opening** and **ending**
  buckets; the director orders within those constraints.

A position the user set is **binding**. The director places only the clips left to it, and a
re-run never rearranges a pinned one (`002_manifests.md`). Where a pin cannot be honoured —
the clip was dropped, or it cannot fill the slot its position lands on — the director surfaces
the conflict rather than quietly resolving it.

#### Ordering is about order, not about time

`sequence` and `weights` say which clip comes before which. They never name a bar or a second:
which bars a clip occupies follows from the slot plan and the music grid (`006_music.md`), and
a user-facing position that meant a bar index would silently point at a different clip whenever
the music analysis changed.

**`strict`** — `sequence` is candidate ids in reel order: `sequence[0]` comes before
`sequence[1]`, and so on. It need not cover the reel; the director fills what is left by its own
rules, around and after the pinned clips.

What binds is the order and not the slot number. Slots are one, two or three bars, so a pinned
clip may be too short for the one its turn lands on; it then takes the next slot that fits
rather than losing its place in the sequence. A clip no remaining slot can hold gives up its
turn — reported, and without blocking everything behind it.

**`weighted`** — a weight is a number from 0 to 100 giving a clip's place along the reel, low
first. It is a relative composition, not a slot number:

- Equal weights are a **batch**: the user says "these three go early", and the director orders
  within the batch.
- A clip with no weight is placed at the director's discretion, but never before the
  lowest-weighted clip and never after the highest-weighted one. Weighting anything therefore
  brackets everything else inside it.
- Free positions between two weighted clips are distributed in proportion to the gap between
  their weights, so 10 → 50 takes about twice the room of 50 → 70.
- With exactly one weighted clip, it anchors at its proportional position — weight 60 of a ten
  clip reel sits around clip six — and free clips fill both sides.

`opening` and `ending` are shorthand for weight 0 and weight 100, so the page can offer "send
to the start" next to the weight control without a second concept underneath it.

Weights here order the reel. They are unrelated to the scoring weights in `project.json`, which
decide how good a clip is rather than where it goes.

### 5. Final tweaks

After a render: the EDL laid over the music waveform with section bands, showing which clip
occupies which bars. Supported edits are add, remove, swap, reorder, and **merge a clip into
its neighbour** — the operations that keep the bar grid intact. Anything more expressive is a
conversation with the agent, not a widget.

Merge exists specifically so the one-bar opening (`006_music.md`) can be undone: it is a
default chosen because the alternative is an arbitrary cut, not because two seconds is always
right, and the viewer is the one who can see whether it works.

## Contract with the agent

- The server never decides anything; it only records what the human did.
- `review.json.completed` is a signal, not a lock. The agent MAY proceed without it, and MUST
  say so when it does.
- Free-text notes per candidate are passed through verbatim for the agent to interpret
  ("this is the same setup as c012", "start half a second later").

## Accessibility and robustness

- Every control reachable by keyboard; the card grid is a list, not a canvas.
- The page MUST render usefully with no proxy available for a candidate, falling back to the
  filmstrip image.
- Autosave failures surface in the page rather than failing silently — the user must never
  believe a verdict was recorded when it was not.
