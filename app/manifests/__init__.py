"""Pydantic models for every manifest in `spec/002_manifests.md`.

The models are authoritative: the CLI validates on read and on write, so a manifest that
parses is one the next stage can rely on.
"""
