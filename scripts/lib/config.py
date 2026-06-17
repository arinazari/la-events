"""Config loading for the la-events scripts — the one place that reads YAML.

Resolves relative paths against the repo root so callers can pass bare names
("profile.yaml", "taste.yaml") regardless of cwd. Degrades gracefully: if
PyYAML or the file is missing, returns {} (callers fall back to defaults).
"""

from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - degrade gracefully
    yaml = None

# scripts/lib/config.py -> scripts/lib -> scripts -> repo root
REPO = Path(__file__).resolve().parent.parent.parent


def load_yaml(path) -> dict:
    """Load a YAML file as a dict. Relative paths resolve against the repo root.
    Returns {} if PyYAML is unavailable or the file doesn't exist."""
    p = Path(path)
    if not p.is_absolute():
        p = REPO / p
    if yaml is None or not p.exists():
        return {}
    with p.open() as f:
        return yaml.safe_load(f) or {}


def load_profile(path="profile.yaml") -> dict:
    """Place/person infrastructure config (ids, geo, scoring mechanics)."""
    return load_yaml(path)


def load_taste(path="taste.yaml") -> dict:
    """Taste content (artists_tracked, venues_loved, pinned_series, ...)."""
    return load_yaml(path)
