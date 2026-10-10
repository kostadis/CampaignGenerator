# Scheduler fixtures

This directory reserves file-backed scheduler fixtures for #549.  The primary
contract seam is intentionally in `tests/conftest.py`: it needs no socket,
provider SDK, or wall-clock delay, while still recording endpoint dispatches.

Run records belong in this directory only when a test needs a persisted input;
otherwise tests construct their small record inline so the behavior under test
is immediately visible.
