"""Build and exercise a real, non-editable CampaignGenerator wheel."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class InstalledDistribution:
    wheel: Path
    python: Path
    scripts: Path
    away: Path

    def run(
        self, *args: str, check: bool = True, env_extra: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            args, cwd=self.away, env=env, text=True, capture_output=True, check=check
        )

    def members(self) -> set[str]:
        with zipfile.ZipFile(self.wheel) as archive:
            return set(archive.namelist())


def build_installed_distribution(root: Path, python: str | None = None) -> InstalledDistribution:
    """Build, install, and return an environment isolated from the checkout.

    ``root`` must be a disposable temporary directory. A caller may set
    ``UV_CACHE_DIR`` to a writable populated cache for offline validation.
    """
    root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    wheel_dir = root / "dist"
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir), str(REPO_ROOT)],
        cwd=root, env=env, check=True, capture_output=True, text=True,
    )
    wheels = list(wheel_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise AssertionError(f"expected one wheel, found {wheels}")
    venv = root / "venv"
    subprocess.run(
        ["uv", "venv", "--python", python or sys.executable, str(venv)],
        cwd=root, env=env, check=True, capture_output=True, text=True,
    )
    scripts = venv / "bin"
    installed_python = scripts / "python"
    subprocess.run(
        ["uv", "pip", "install", "--compile-bytecode", "--python", str(installed_python), str(wheels[0])],
        cwd=root, env=env, check=True, capture_output=True, text=True,
    )
    away = root / "away"
    away.mkdir()
    return InstalledDistribution(wheels[0], installed_python, scripts, away)
