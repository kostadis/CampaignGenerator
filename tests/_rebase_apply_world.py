"""A rebase ready to apply, built once and cloned per test (spec 040 T028/T029). Not collected: no ``test_`` prefix.

:func:`build_template` runs the whole real chain (inspect, prepare, repairs, hold, decide, check, stage, real
claims, signoffs, review handoff) and stops BEFORE ``grounding apply``.  :func:`clone` copies the campaign tree so
each test mutates its own copy.  Nothing in claims, review bindings or promotion is mocked.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pipelines.summary_native.delta import baseline as bl, grounding_publish as gp
from pipelines.summary_native.delta.plan import load_plan, plans_dir
from tests import _rebase_fixture as rf
from tests.test_delta_grounding_e2e import run


class ApplyWorld:
    def __init__(self, root: Path, fx, rebased, cap) -> None:
        self.root, self.fx, self.rebased, self.cap = root, fx, rebased, cap
        self.backup = root.parent / (root.name + ".pristine")
        shutil.copytree(root, self.backup, symlinks=True)
        self.old_generation = fx.generation_id
        self.plan_id = rebased.plan_id
        self.preview_sha = rebased.applied["preview_sha256"]

    def reset(self) -> "ApplyWorld":
        """Put the campaign back exactly as built.  The path stays the same: a review binds the campaign's location."""
        shutil.rmtree(self.root)
        shutil.copytree(self.backup, self.root, symlinks=True)
        return self

    def plan(self):
        return load_plan(plans_dir(self.root), self.plan_id)

    def apply(self, *, preview_sha: str | None = None, expect: int = 0) -> dict:
        with self.cap.active():
            return run(self.cap, self.root, "grounding", "apply", "--plan", self.plan_id,
                       "--preview-sha", preview_sha or self.preview_sha, expect=expect)

    def active(self) -> str:
        return bl.bind(self.root).generation_id

    def candidates(self) -> dict[str, bytes]:
        return gp.load_inputs(self.root, self.plan_id)[0]


def build_template(tmp_path: Path, cap, mp) -> ApplyWorld:
    with cap.active():
        fx = rf.build(tmp_path, cap, mp, pending_ch6=False)
        rebased = rf.do_rebase(fx, cap, apply=False)
    return ApplyWorld(fx.root, fx, rebased, cap)
