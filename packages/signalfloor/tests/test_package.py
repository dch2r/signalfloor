import signalfloor


def test_version_matches_installed_metadata() -> None:
    assert signalfloor.__version__ == "0.0.1"
