# P4 Stable Implementation Report

Release date: 2026-07-24

Supported entrance effects: `appear`, `fade`, `wipe`, `fly_in`, `zoom`.
Emphasis and exit effects are rejected with 422; the editor does not present them.

Backend release: `fa85b313`; frontend release: `80b8c9b`.

Key fixes: strict effect/parameter validation, explicit target ownership, no mixed slide triggers, persisted per-object triggers, serialized editor saves, export flush, and no editor request for transient `ppt-*` routes.
