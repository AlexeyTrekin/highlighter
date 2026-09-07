---
description: "Python-specific conventions: PEP 8, module-function pattern, alembic migrations, containerized tests. Applies during delivery, stabilization, and review when files under app/, alembic/, or tests/ are touched."
applyTo: "{app,alembic,tests}/**"
---

# Python Language Pack

Layered on top of `instructions/delivery.md`, `instructions/stabilization.md`, and `instructions/review.md`. Read this pack whenever the change touches Python sources, tests, or alembic migrations.

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

## Migrations (alembic)
- Keep migrations in `alembic/versions/` deterministic and human-reviewable.
- Additive by default; destructive operations require an explicit WAL note explaining the data-loss risk and the rollback plan.
- After autogenerate, hand-edit the migration to remove noise (e.g., spatial-index duplicates already created by GeoAlchemy2).

## Tests
- All tests (unit and integration) MUST run inside the project test container — never run the suite from a host venv.
- Integration tests MAY launch sidecar containers for external dependencies and mock servers via docker-compose.
- Match the test entry points listed in `AGENTS.md` COMMANDS section (`agent-make test`, `agent-make utest`, `agent-make itest`, `agent-make test-attach`). All invocations go through `agent-make` — see AGENTS.md MAKE COMMAND POLICY.

## Stabilization Checklist (Python-specific, per fix cycle)
- Imports remain at file top (PEP 8) — no lazy imports introduced by the fix.
- Module-function pattern preserved; no incidental class wrapping.
- No new lazy imports inside functions unless documented as a circular-dependency workaround.

## Review Checklist Add-ons (Python-specific)
- `async` correctness: no blocking I/O on async paths (`requests`, `time.sleep`, sync DB drivers); use `asyncio.to_thread` for unavoidable sync calls.
- SQLAlchemy session lifetime: session-per-request, no session leak across services.
- Pydantic models: `from_attributes=True` where ORM compatibility is needed; avoid silent type coercion in request schemas.
