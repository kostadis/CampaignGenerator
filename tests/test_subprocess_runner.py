import asyncio
import json
import sys

import pytest

from server.subprocess_runner import BoundedJSONError, run_bounded_json, stream_subprocess


def test_bounded_json_accepts_one_object_without_run_log(tmp_path):
    value = asyncio.run(run_bounded_json(
        [sys.executable, "-c", "import json; print(json.dumps({'ok': True}))"],
        cwd=str(tmp_path), save_run_log=False,
    ))
    assert value == {"ok": True}
    assert not (tmp_path / "logs").exists()


def test_bounded_json_enforces_output_limit(tmp_path):
    with pytest.raises(BoundedJSONError) as raised:
        asyncio.run(run_bounded_json(
            [sys.executable, "-c", "print('x' * 5000)"],
            cwd=str(tmp_path),
            max_output_bytes=64,
            save_run_log=False,
        ))
    assert raised.value.category == "output_limit"


def test_stream_subprocess_save_run_log_false_preserves_terminal_result(tmp_path):
    async def consume():
        return [chunk async for chunk in stream_subprocess(
            [sys.executable, "-c", "print('done')"], cwd=str(tmp_path), save_run_log=False,
        )]

    chunks = asyncio.run(consume())
    done = [chunk for chunk in chunks if chunk.startswith("event: done")]
    assert len(done) == 1 and '"returncode": 0' in done[0]
    assert not (tmp_path / "logs").exists()
