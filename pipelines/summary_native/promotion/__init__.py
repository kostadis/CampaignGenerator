"""Deterministic whole-bundle promotion primitives.

This package must remain importable without loading candidate extraction or any
model client.  Publication consumes reviewed, persisted claim results through
typed records; it never invokes semantic extraction.
"""
