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

### 4. Ordering

Optional and skippable. Three modes:

- `auto` — the director decides. Default.
- `strict` — the user drags kept clips into an explicit sequence.
- `weighted` — the user sets relative weights and fills **opening** and **ending** buckets;
  the director orders within those constraints.

### 5. Final tweaks

After a render: the EDL laid over the music waveform with section bands, showing which clip
occupies which bars. Supported edits are add, remove, swap, and reorder — the operations that
keep the bar grid intact. Anything more expressive is a conversation with the agent, not a
widget.

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
