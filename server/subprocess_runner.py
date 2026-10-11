"""Re-export of :mod:`campaignlib.subprocess_runner`.

The runner moved to ``campaignlib`` so engine-layer code (the summary-native
review web app) can launch CLIs without importing the web server
(tests/test_layering.py). Server routes keep importing it from here.
"""

from campaignlib.subprocess_runner import (  # noqa: F401
    GRACE_SECONDS,
    BoundedJSONError,
    _killpg_safe,
    _log_stem,
    _redact_text,
    _redactable_prefix,
    _save_run_log,
    classify_result,
    console_script,
    python_exe,
    run_bounded_json,
    run_command_capture,
    sse_error_stream,
    stream_subprocess,
)
