"""Renderer-agnostic slide design layer.

Holds the design tokens (``design_system`` — ``Theme``/``resolve_theme``/dark-light
rhythm), the text-capacity model (``fit`` — ``CAPACITIES`` + line-fit estimator),
and the content-shaping helpers (``content`` — lead/body derivation, item
normalization, fit-trim). Consumed by the native renderer and the planner; no
HTML/Chrome dependency.
"""
