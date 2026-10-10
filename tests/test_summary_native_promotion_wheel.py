"""Installed wheel smoke for promotion, migration, and claims entry points."""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers.installed_distribution import InstalledDistribution, build_installed_distribution


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def installed_distribution(tmp_path_factory: pytest.TempPathFactory) -> InstalledDistribution:
    return build_installed_distribution(
        tmp_path_factory.mktemp("promotion-installed-wheel")
    )


@pytest.mark.parametrize(
    ("script", "arguments", "marker"),
    (
        ("summary_native", ("promote", "--help"), "--check-report"),
        ("summary_native", ("claims", "selection", "save", "--help"), "--reviewer"),
        ("migrate_grounding_bundle", ("--help",), "--recover"),
    ),
)
def test_installed_console_dispatch_runs_away_from_checkout(
    installed_distribution: InstalledDistribution,
    script: str,
    arguments: tuple[str, ...],
    marker: str,
) -> None:
    result = installed_distribution.run(
        str(installed_distribution.scripts / script), *arguments,
    )
    assert marker in result.stdout
    assert installed_distribution.away != REPO_ROOT


def test_wheel_packages_claims_modules_and_private_review_assets(
    installed_distribution: InstalledDistribution,
) -> None:
    members = installed_distribution.members()
    required = {
        "pipelines/summary_native/claims/cli.py",
        "pipelines/summary_native/claims/extract.py",
        "pipelines/summary_native/claims/imports.py",
        "pipelines/summary_native/claims/report.py",
        "pipelines/summary_native/review/web/viewer.html",
        "pipelines/summary_native/review/web/viewer.js",
        "pipelines/summary_native/review/web/viewer.css",
    }
    assert required <= members
    probe = installed_distribution.run(
        str(installed_distribution.python), "-c",
        (
            "from importlib.resources import files; "
            "import pipelines.summary_native.claims.cli as claims; "
            "root=files('pipelines.summary_native.review.web'); "
            "assert all(root.joinpath(name).read_bytes() for name in ('viewer.html','viewer.js','viewer.css')); "
            "print(claims.__file__)"
        ),
    )
    installed_path = Path(probe.stdout.strip()).resolve()
    assert not installed_path.is_relative_to(REPO_ROOT)
    assert installed_path.is_relative_to(installed_distribution.wheel.parent.parent)
