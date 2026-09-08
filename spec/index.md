# Specification Index

This folder holds the project specification, ordered by dependency. Agents read `index.md`
first to find the documents relevant to a task, then dive into them.

The project turns amateur HEMA tournament footage into a short, music-cut highlight reel.
Its central idea: **the pipeline produces a markup sequence (`edl.json`); the video is a
deterministic render of it.** Everything upstream exists to fill that markup in well.

| document | covers | read it when |
|---|---|---|
| [001_goal.md](001_goal.md) | product goal, inputs/outputs, `event` vs `personal` mode, human-input budget, what is out of scope and what is deferred | any scope question |
| [002_manifests.md](002_manifests.md) | **the data contract** — project layout and every manifest schema, including `edl.json` | touching any file the pipeline reads or writes |
| [003_pipeline.md](003_pipeline.md) | stage graph, ordering constraints, idempotency and resume, long-recording path | adding or reordering a stage |
| [004_stack.md](004_stack.md) | host runtime (no container), dependencies, optional backends, repo layout | dependency or infrastructure decisions |
| [005_scoring.md](005_scoring.md) | what a "good moment" is: camera compensation, halt detection, closing speed, quality gates, target identification, benchmark | changing how candidates are found or ranked |
| [006_music.md](006_music.md) | grid fitting, sections, chords, mood, and the mapping rules the director follows | anything touching the music timeline |
| [007_review_ui.md](007_review_ui.md) | the local review server and its views: verdicts, trims, ordering, final tweaks | changing what the human sees or does |
| [008_render.md](008_render.md) | cumulative timing, tracked crop, stabilisation, assembly, automated QA | changing pixels or cut placement |
| [009_agent_surface.md](009_agent_surface.md) | CLI as the contract, MCP as a wrapper, what the agent is for | changing how an agent drives the system |

Keep documents stable. When a task needs behavior not yet covered, propose a spec delta and
get explicit approval before editing (see the Specification Coverage Gate in `AGENTS.md`).
