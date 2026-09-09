# tournament-highlight

Turns a folder of HEMA tournament clips and a music track into a ~60-second highlight reel cut
to the beat.

It finds the moments worth showing (exchanges that end in a halt, plus the walk-ons and salutes
that suit a quiet intro), fits a bar grid to the music, and cuts every clip on a bar line. You
review the candidates in a local web page — keep, drop, trim, reorder — and the reel is rebuilt
from your decisions.

The pipeline never decides silently: anything it could not do the way you asked is reported.

---

## Install

### 1. Prerequisites

| what | why | check |
|---|---|---|
| Python **3.12+** | the pipeline | `python3 --version` |
| **ffmpeg** built with **libvidstab** | rendering and stabilisation | `ffmpeg -filters \| grep vidstab` |
| **ffprobe** | reading source metadata | `ffprobe -version` |

**macOS.** Homebrew's default `ffmpeg` formula is built *without* libvidstab, so the plain
`brew install ffmpeg` is not enough. Install the full build and put it first on your `PATH`:

```bash
brew install ffmpeg-full
export PATH="$(brew --prefix)/opt/ffmpeg-full/bin:$PATH"
```

`ffmpeg-full` is keg-only, which is why the `PATH` line is needed — add it to your shell profile
if you want it to stick.

**Debian / Ubuntu.** The distribution ffmpeg includes libvidstab:

```bash
sudo apt install ffmpeg
```

### 2. The project itself

```bash
make venv
```

This creates `.venv/` and installs the package with its dev extras. Everything below runs from
that virtualenv — either through `make`, or directly as `.venv/bin/hlreel …`.

### 3. Check the host

```bash
make doctor
```

Every line must say `ok`:

```
ok    python   3.12 (need >= 3.12)
ok    ffmpeg   /usr/local/bin/ffmpeg (libvidstab present)
ok    ffprobe  /usr/local/bin/ffprobe
ok    yolov8n.onnx …/models/yolov8n.onnx
```

`doctor` exits `3` if something is missing and tells you what to install. It is worth running
before a long job rather than finding out an hour in.

### 4. Fetch the detector weights

```bash
.venv/bin/hlreel fetch-models
```

One YOLOv8n ONNX file (~12 MB), used to find the fighters. The weights are not in the
repository — they are large and not ours to redistribute — so this is the **only** command that
touches the network. It verifies a SHA-256 pin on what it downloads.

---

## Run

The whole flow, end to end. Substitute your own paths.

### 1. Create a project

```bash
.venv/bin/hlreel init projects/my-event --music ~/music/track.mp3 --duration 60
```

A project is just a directory: manifests, previews and renders all live inside it, and it is the
entire state. There is no database. `--duration` is the reel length you want, in seconds.

### 2. Add footage

```bash
.venv/bin/hlreel add projects/my-event ~/footage/tournament/
```

Takes files or directories. **Your videos are referenced, not copied** — the project stores
absolute paths, so moving or deleting the originals breaks it.

### 3. Build

```bash
.venv/bin/hlreel run projects/my-event
```

This runs every stage in order. Rough timings measured on 50 clips totalling 7.6 minutes of
1080p footage, on a laptop CPU:

| stage | what it does | time |
|---|---|---|
| `analyze` | decodes every source, detects fighters, measures motion | ~4 min |
| `music` | fits the bar grid, finds sections | ~7 s |
| `candidates` | proposes windows and scores them | ~2 s |
| `proxies` | 360p previews, posters and filmstrips for the review page | ~13 s |
| `director` | chooses clips and writes `edl.json` | instant |
| `render` | cuts, stabilises, muxes the music | ~9 min |

`analyze` is the only stage that reads whole videos, and it is resumable per source — an
interrupted run picks up where it stopped. `render` is slow because stabilisation is a two-pass
ffmpeg job per clip.

You now have `projects/my-event/highlight_v1.mp4`. Watch it before reviewing anything: the
review page is much quicker once you know what the reel already looks like.

### 4. Review

```bash
make run PROJECT=projects/my-event
```

Starts the review server, prints its URL, and blocks until you stop it with `Ctrl-C`. Open
<http://127.0.0.1:8420/> yourself. It binds to loopback and nothing else — it serves your own
footage with no authentication, so it is not for sharing.

Nothing here is required. An untouched project still renders; the page is an override, not a
gate, and every interaction saves as you make it.

**Per clip:**

| key | meaning |
|---|---|
| `1` | **Drop** — never use this |
| `2` | **Agent's call** — the default |
| `3` | **Keep** — must appear |

`J` / `K` move between cards; hovering a card plays it. Clips the pipeline already rejected are
collapsed at the bottom with the reason — expand that section to rescue one, which overrides the
quality gate that dropped it.

**Trim** narrows a clip to the seconds you want. Dragging a handle seeks the preview, and the
readout tells you what you will actually get — *"3.10s of 4.20s — cuts to 1 bar (2.00s), ending
where you set 'end'"* — because clips are cut in whole bars, and a trim shorter than one bar
cannot be used at all. A trim binds: nothing downstream will reach outside it.

**Ordering** is optional, and has three modes:

- **Agent's call** — the director decides.
- **Sequence** — pin clips into an explicit order. Drag to rearrange, or `Alt`+`↑`/`↓` on a
  focused entry. You need not order the whole reel; the director fills the rest around what you
  set.
- **Weights** — give a clip a position from 0 to 100. 0 opens the reel, 100 closes it, equal
  weights mean "these go together, you pick the order among them". Unweighted clips are placed
  between your lowest and highest.

Ordering is about *order*, never about time: which bars a clip lands on stays the director's
job.

### 5. Rebuild with your decisions

```bash
.venv/bin/hlreel run projects/my-event
```

The same command. It notices `review.json` changed, re-cuts the edit and re-renders — the
expensive `analyze` stage is not repeated. You get `highlight_v2.mp4`; reels are versioned
rather than overwritten, so you can compare.

**Read the warnings.** Anything the pipeline could not honour is printed to stderr:

```
warning: c006 was asked for but is not in the reel — only 1.45s after trimming; the shortest slot is 2.00s
```

A keep or a pin that silently vanished would be the worst outcome available, so it never
happens quietly.

### 6. Check the QA report

`render` prints one line per automated check — frozen frames, cuts off the bar grid, clips
straddling a section boundary, duplicate footage, whether the fade lands on a fight clip. `FAIL`
blocks calling the reel finished; `WARN` is worth a look.

```bash
.venv/bin/hlreel status projects/my-event --json
```

...reports where every stage stands.

---

## Useful extras

```bash
.venv/bin/hlreel music projects/my-event      # the fitted tempo, bar length and sections
.venv/bin/hlreel edl projects/my-event --show # the edit, clip by clip, with the reason for each
.venv/bin/hlreel render projects/my-event     # re-render without re-cutting
.venv/bin/hlreel run projects/my-event --stage director --force
```

`edl.json` is the contract: the renderer is a pure function of it. You can hand-edit it and
re-render, and `--set` will load one back.

---

## When something goes wrong

**`doctor` fails on ffmpeg.** You have an ffmpeg without libvidstab. See the macOS note above —
`brew install ffmpeg` is the usual cause.

**`run` says "nothing (already done)".** Every stage is complete and nothing upstream changed.
Force a single one with `--stage <name> --force`. Prefer that to a bare `--force`, which re-runs
`analyze` as well and re-decodes every source — the slowest thing the pipeline does.

**The reel is shorter than the track.** There were not enough usable clips to fill it. The reel
ends on its last clip and the music fades down with the picture rather than being cut off.

**A clip you kept is missing.** Look for the `warning:` line — it names the rule that excluded
it, measured against the reel that was actually built.

**Two things at once.** One writer per project directory. If a `run` reports the project is
locked and you are sure nothing else is running, delete the `.lock` file inside it.

**`make bench` says "No such command".** Expected for now. `make help` lists it because the
`Makefile` is fixed ahead of the code it calls; the benchmark itself arrives with WAL step 2.2.

---

## Repository layout

```
spec/       the specification, ordered by dependency; start at spec/index.md
app/        the pipeline
tests/      unit and integration tests
WAL.md      the working journal — every decision and why it was made
projects/   your working projects (gitignored)
models/     fetched detector weights (gitignored)
```

`make test` runs the suite, `make lint` checks style. Contributors should read `AGENTS.md`
first — it describes the workflow this repository is built around.
