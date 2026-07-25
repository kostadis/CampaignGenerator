"""Shared constants for the one-shot config migration CLIs.

Four CLIs — ``migrate_session_doc``, ``migrate_ensemble_config``,
``migrate_grounding_config`` and ``migrate_platform_config`` — lift data out of
a pre-isolation ``ui_state.yaml`` into the dedicated document its owning
service now uses. They all need the source filename, and they used to import it
from ``server/config_service.py``.

That module is gone (``docs/config/ui-state-retirement.md``): the server no
longer reads ``ui_state.yaml`` at all. **The migrators still do, and must.**
They read it RAW via ``yaml.safe_load`` — deliberately never through a typed
model — precisely so they can rescue fields no live schema declares any more.
Retiring the reader does not retire the rescuers: a campaign restored from an
old backup, or one that was never migrated, still needs them.

So the constant lives here, in a module owned by the migrators themselves,
rather than in a service that would have to keep existing to host it.
"""

from __future__ import annotations

UI_STATE_NAME = "ui_state.yaml"
