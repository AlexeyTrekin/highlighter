# 009 — Agent surface

The intended way to use this project is a conversation: the user tells an agent what they
want, the agent runs stages and hands back a URL to review and a reel to watch.

## The CLI is the contract

Every capability is a CLI command. This keeps the toolbox host-agnostic — Claude Code, any
other agent, a shell script or a cron job drive it identically — and makes every step
reproducible by hand.

```
hlreel doctor                         # host prerequisites; exit 3 when one is missing
hlreel version
hlreel init <dir> --mode event|personal [--music PATH] [--target "black jacket"]
hlreel add <dir> <paths...>
hlreel run <dir> [--stage STAGE] [--force]
hlreel review <dir> [--port N]        # starts the server, prints the URL
hlreel edl <dir> [--show|--set FILE]
hlreel render <dir> [--out PATH]
hlreel status <dir>
hlreel bench <fixtures>
```

`doctor` is load-bearing rather than a convenience: with no container, the host's own tools
are part of the contract (`004_stack.md`), and `doctor` is where that contract is checked.

Rules:

- Every command is **non-interactive**. No prompts, no TTY assumptions. Steering comes from
  flags and from `review.json`.
- Every command prints a machine-readable summary (`--json`) as well as human text. An agent
  should never have to parse prose.
- Exit codes are meaningful: `0` success, `1` stage failure, `2` bad input, `3` blocked on a
  missing prerequisite.
- Long stages stream progress to stderr and checkpoint to manifests, so a killed run resumes
  (`003_pipeline.md`).

## MCP is a wrapper, not a second implementation

An MCP server exposes the same operations as tools for hosts that support it. It MUST call
the same module-level functions the CLI calls, and add no behaviour of its own. If a
capability exists only over MCP, that is a defect.

## What the agent is for

The parts of this problem that are genuinely judgement, not signal processing:

- **Visual review of candidates** — reading filmstrips and catching what no metric sees:
  opponents out of frame, the camera behind a fighter, a spectator walking through
  (`005_scoring.md`).
- **Directing** — choosing which clip lands on the drop, what opens, what closes, and
  explaining the choice in `edl.json.why`.
- **Interpreting the user's free text** — "this is the same setup as c012", "start half a
  second later", "more of the tall guy in red".

Everything else — detection, flow, grid fitting, rendering — is deterministic code, and the
agent should not be in that loop.

## Media never leaves the machine

Footage and audio are local (`004_stack.md`). An agent MUST NOT upload source media to any
external service. Filmstrips and low-resolution proxies MAY be shown to a vision model when
the user has asked for that, and the user is told which backend is used.

## Talking to the user

- Present the reel with its `edl.json`, the QA warnings, and the upscale note if one applies.
- Say what was decided automatically and what the user could change — an untouched review
  means the agent chose everything, and that should be visible, not implied.
- Never make the user watch a long rough cut and transcribe clip numbers out of it. Numbers
  burned into a rough reel are for referring back to, not the review mechanism.
