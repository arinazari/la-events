"""Shared library for the la-events scripts.

Single source of truth for the bits that used to be duplicated / hardcoded:
- config.py  — YAML loading + repo-root resolution (profile.yaml, taste.yaml)
- scoring.py — the taste-ranking heuristic (was inline in build_dashboard.py)
- dedupe.py  — fuzzy event dedupe (was done by hand in the digest)
"""
