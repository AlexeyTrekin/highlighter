# Specification Index

This folder holds the project specification, ordered by dependency. Agents read
`index.md` first to find the documents relevant to a task, then dive into them.

Suggested ordering convention (rename/extend to fit your project):

- `001_goal.md` — product goal and scope (or extracted domain constraints for an existing project)
- `002_api.md` — external/internal API contracts
- `003_db.*` — data model (DBML, schema, ERD)
- `004_stack.md` — language, framework, runtime, infra decisions
- `005_*.md` — interactions, integrations, and subsequent decisions with rationale

Keep documents stable. When a task needs behavior not yet covered, propose a spec
delta and get explicit approval before editing (see the Specification Coverage Gate
in `AGENTS.md`).

> This is a scaffolded stub. Replace it with your real specification.
> A worked example lives in the toolkit under `templates/example-spec/`.
