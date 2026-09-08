---
description: "Python-specific conventions: PEP 8, module-function pattern, JSON-manifest persistence, venv-based tests. Applies during delivery, stabilization, and review when files under app/ or tests/ are touched."
applyTo: "{app,tests}/**"
---

# Python Language Pack

Layered on top of `instructions/delivery.md`, `instructions/stabilization.md`, and `instructions/review.md`. Read this pack whenever the change touches Python sources or tests.

## Style
- Follow PEP 8.
- Keep imports at file top — no lazy imports inside functions unless a circular dependency requires it.
- Type-hint public functions and module-level constants.

## Architecture Pattern: Module-Level Functions
Prefer module-level functions over classes unless OOP is genuinely necessary (state machines, frameworks that require classes, polymorphism with shared invariants). Use `import module` and call `module.function()` rather than importing the function directly.

Good
```python
# file: my_service.py
def do_smth():
    pass

# file: my_router.py
from service import my_service

def do_smth_request():
    return my_service.do_smth()
```

Bad
```python
# file: my_service.py
class MyService:
    def do_smth(self):
        pass

# file: my_router.py
from service.my_service import MyService

def do_smth_request():
    my_service = MyService()
    return my_service.do_smth()
```

## Persistence
There is no database (`spec/004_stack.md`). State lives in the project directory as JSON
manifests defined by `spec/002_manifests.md`, each with a pydantic model that validates it on
read and on write. A change that wants an ORM, a migration tool or a schema table is a spec
change, not an implementation detail — stop and surface it.

Manifests are written atomically (temp file + rename) so an interrupted stage never leaves a
half-parsed file behind.

## Tests
- All tests run on the host in the project virtualenv (`.venv/`), created by `agent-make venv`. Never install project dependencies into the system interpreter.
- Integration tests may start the project's own services (e.g. the review server) as subprocesses or via the ASGI test client. They must not require any external daemon that `agent-make doctor` does not check for.
- Tests that need `ffmpeg`/`ffprobe` MUST skip cleanly when the binary is missing, so a host without it still gets a meaningful unit-test run.
- Match the test entry points listed in `AGENTS.md` COMMANDS section (`agent-make test`, `agent-make utest`, `agent-make itest`). All invocations go through `agent-make` — see AGENTS.md MAKE COMMAND POLICY.

## Stabilization Checklist (Python-specific, per fix cycle)
- Imports remain at file top (PEP 8) — no lazy imports introduced by the fix.
- Module-function pattern preserved; no incidental class wrapping.
- No new lazy imports inside functions unless documented as a circular-dependency workaround.

## Review Checklist Add-ons (Python-specific)
- `async` correctness: no blocking I/O on async paths (`requests`, `time.sleep`, CPU-bound decode or ffmpeg calls); use `asyncio.to_thread` for unavoidable sync work in the review server.
- Pydantic models: manifest models mirror `spec/002_manifests.md` exactly; avoid silent type coercion, and keep times as floats in seconds rather than accepting stringly-typed input.
- Subprocess calls to `ffmpeg`/`ffprobe` pass argument lists, never shell strings, and always set a timeout.
