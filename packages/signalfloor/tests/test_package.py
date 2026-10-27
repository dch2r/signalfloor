import tomllib
from pathlib import Path

import signalfloor


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]

    assert signalfloor.__version__ == expected


def test_package_license_matches_repo_license() -> None:
    # The package ships its own copy because builds cannot reach files outside its folder.
    package_root = Path(__file__).parents[1]
    repo_root = package_root.parents[1]

    assert (package_root / "LICENSE").read_bytes() == (repo_root / "LICENSE").read_bytes()
