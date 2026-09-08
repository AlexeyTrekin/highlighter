"""Model files the pipeline needs but does not ship.

Weights are large and not ours to redistribute, so they live in a gitignored `models/` beside
the code and are fetched on demand. `doctor` reports a missing one as a prerequisite failure
rather than letting a stage discover it minutes into an analysis run.
"""

import hashlib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

MODELS_DIR: Path = Path(__file__).resolve().parent.parent / "models"
DOWNLOAD_TIMEOUT_S: int = 120
CHUNK_BYTES: int = 1 << 16


@dataclass(frozen=True)
class Asset:
    """A file to fetch, and how to know it arrived intact."""

    name: str
    url: str
    sha256: str
    purpose: str

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.name


# The digest pins the file against later change at the source. It was recorded from the first
# download rather than published by an authority, so it is protection against drift, not proof
# of provenance — see `spec/004_stack.md`.
YOLOV8N = Asset(
    name="yolov8n.onnx",
    url=(
        "https://raw.githubusercontent.com/Hyuto/yolov8-onnxruntime-web/"
        "master/public/model/yolov8n.onnx"
    ),
    sha256="505648ada344cd9f3f31e51d49c489c070819bc96cc758258a8fd51488e00579",
    purpose="person detection (spec/005_scoring.md)",
)

REGISTRY: dict[str, Asset] = {YOLOV8N.name: YOLOV8N}


class AssetError(RuntimeError):
    """An asset could not be fetched or did not match its digest."""


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def available(asset: Asset) -> bool:
    return asset.path.is_file() and asset.path.stat().st_size > 0


def verify(asset: Asset) -> tuple[bool, str]:
    """Whether the local copy is present and matches its pin."""
    if not available(asset):
        return False, "not downloaded"
    if not asset.sha256:
        return True, f"{asset.path} (unpinned; digest {digest(asset.path)[:16]})"
    found = digest(asset.path)
    if found != asset.sha256:
        return False, f"{asset.path} does not match its pinned digest (found {found[:16]})"
    return True, str(asset.path)


def fetch(asset: Asset, *, force: bool = False) -> Path:
    """Download the asset unless a good copy is already there.

    Lands on a temp name and is renamed into place, so an interrupted download never leaves a
    truncated file that later looks present.
    """
    if available(asset) and not force:
        ok, _ = verify(asset)
        if ok:
            return asset.path

    if not asset.url.startswith("https://"):
        raise AssetError(f"{asset.name}: refusing to fetch over {asset.url.split(':')[0]}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    partial = asset.path.with_suffix(asset.path.suffix + ".part")
    try:
        with urllib.request.urlopen(asset.url, timeout=DOWNLOAD_TIMEOUT_S) as response:
            partial.write_bytes(response.read())
    except (urllib.error.URLError, OSError) as error:
        partial.unlink(missing_ok=True)
        raise AssetError(f"could not download {asset.name} from {asset.url}: {error}") from error

    if asset.sha256:
        found = digest(partial)
        if found != asset.sha256:
            partial.unlink(missing_ok=True)
            raise AssetError(
                f"{asset.name} downloaded but its digest is {found}, expected {asset.sha256}"
            )

    partial.replace(asset.path)
    return asset.path


def require(asset: Asset) -> Path:
    """The asset's path, or an error naming the command that would fix it."""
    ok, detail = verify(asset)
    if not ok:
        raise AssetError(f"{asset.name}: {detail}")
    return asset.path
