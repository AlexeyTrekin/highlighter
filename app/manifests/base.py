"""Shared manifest behaviour: the universal fields and atomic persistence.

Every manifest in `spec/002_manifests.md` carries `schema_version` and `stage`, and is written
whole or not at all.
"""

import json
import os
import tempfile
from pathlib import Path

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION: int = 1


class Manifest(BaseModel):
    """A JSON document a stage owns."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    schema_version: int = SCHEMA_VERSION
    stage: str


def write(path: Path, manifest: Manifest) -> None:
    """Serialise to `path` atomically.

    A stage that dies mid-write must not leave a half-parsed manifest behind, so the content
    lands in a sibling temp file and is renamed over the target — rename is atomic within a
    filesystem, and the sibling guarantees the same one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = manifest.model_dump(mode="json", by_alias=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=1, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read[T: Manifest](path: Path, model: type[T]) -> T:
    """Parse `path` as `model`, validating on the way in."""
    return model.model_validate_json(path.read_text(encoding="utf-8"))


def dumps(manifest: Manifest) -> str:
    """Canonical JSON text for a manifest.

    Sorted keys and a fixed indent make two runs of a deterministic stage byte-comparable,
    which is how `spec/002_manifests.md` expects director determinism to be checked.
    """
    return (
        json.dumps(
            manifest.model_dump(mode="json", by_alias=True),
            indent=1,
            ensure_ascii=False,
            sort_keys=True,
        )
        + "\n"
    )
