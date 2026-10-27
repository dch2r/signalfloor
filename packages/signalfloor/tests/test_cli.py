import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from signalfloor.cli import EXIT_OK, EXIT_REGRESSION, EXIT_UNTRUSTED, EXIT_USAGE, main


def write_run(path: Path, scores: list[float], id_key: str = "id", score_key: str = "score") -> str:
    lines = [json.dumps({id_key: f"case-{i}", score_key: s}) for i, s in enumerate(scores)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def runs(tmp_path: Path) -> dict[str, str]:
    base = [0.9, 0.8, 0.85, 0.95, 0.7, 0.75, 0.9, 0.8] * 10
    return {
        "base": write_run(tmp_path / "base.jsonl", base),
        "same": write_run(tmp_path / "same.jsonl", base),
        "worse": write_run(tmp_path / "worse.jsonl", [s - 0.2 for s in base]),
        "better": write_run(tmp_path / "better.jsonl", [s + 0.05 for s in base]),
    }


def test_regression_exits_with_code_1(
    runs: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["compare", runs["base"], runs["worse"], "--seed", "0"])

    out = capsys.readouterr().out
    assert code == EXIT_REGRESSION
    assert "verdict     regression" in out
    assert "cases       80" in out
    assert "change      -0.2000  (95% CI" in out


def test_no_change_exits_with_code_0(
    runs: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["compare", runs["base"], runs["same"], "--seed", "0"])

    assert code == EXIT_OK
    assert "verdict     no detectable change" in capsys.readouterr().out


def test_improvement_exits_with_code_0(
    runs: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["compare", runs["base"], runs["better"], "--seed", "0"])

    assert code == EXIT_OK
    assert "verdict     improvement" in capsys.readouterr().out


def test_json_output(runs: dict[str, str], capsys: pytest.CaptureFixture[str]) -> None:
    main(["compare", runs["base"], runs["worse"], "--seed", "0", "--format", "json"])

    data = json.loads(capsys.readouterr().out)
    assert data["verdict"] == "regression"
    assert data["n_cases"] == 80
    assert data["delta"] == pytest.approx(-0.2)
    assert data["ci_low"] <= data["ci_high"] < 0


def test_options_are_passed_through(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = write_run(tmp_path / "b.jsonl", [1.0, 0.0, 1.0], "case", "acc")
    cand = write_run(tmp_path / "c.jsonl", [1.0, 0.0, 1.0], "case", "acc")

    code = main(
        [
            "compare",
            base,
            cand,
            "--id-key=case",
            "--score-key=acc",
            "--confidence=0.9",
            "--resamples=100",
            "--format=json",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK
    assert data["confidence"] == 0.9
    assert data["n_resamples"] == 100


def test_bad_file_exits_with_code_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = write_run(tmp_path / "b.jsonl", [1.0, 0.0])
    bad = tmp_path / "bad.jsonl"
    bad.write_text("oops\n", encoding="utf-8")

    code = main(["compare", base, str(bad)])

    err = capsys.readouterr().err
    assert code == EXIT_USAGE
    assert err.startswith("signalfloor: error: ")
    assert "bad.jsonl:1: invalid JSON" in err


def test_mismatched_runs_exit_with_code_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = write_run(tmp_path / "b.jsonl", [1.0, 0.0, 1.0])
    cand = write_run(tmp_path / "c.jsonl", [1.0, 0.0])

    assert main(["compare", base, cand]) == EXIT_USAGE
    assert "same cases" in capsys.readouterr().err


def test_bad_option_value_exits_with_code_2(
    runs: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["compare", runs["base"], runs["same"], "--confidence", "2"]) == EXIT_USAGE
    assert "confidence" in capsys.readouterr().err


def test_missing_command_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == EXIT_USAGE


def test_runs_as_installed_command(runs: dict[str, str]) -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "signalfloor", "compare", runs["base"], runs["worse"]],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == EXIT_REGRESSION
    assert "verdict     regression" in proc.stdout


def write_labels(path: Path, values: Sequence[object]) -> str:
    lines = [json.dumps({"id": f"case-{i}", "label": v}) for i, v in enumerate(values)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_calibrate_trusted_judge_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    human = [1, 2, 3, 4, 5] * 40
    judge = list(human)
    judge[0] = 2
    j = write_labels(tmp_path / "j.jsonl", judge)
    h = write_labels(tmp_path / "h.jsonl", human)

    code = main(["calibrate", j, h, "--weights", "quadratic", "--seed", "0"])

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "cases       200" in out
    assert "labels      1, 2, 3, 4, 5" in out
    assert "weights     quadratic" in out
    assert "kappa       0.99" in out
    assert "judge bias  +0.005  (more lenient than humans)" in out
    assert "verdict     trusted (threshold 0.6)" in out


def test_calibrate_always_pass_judge_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    j = write_labels(tmp_path / "j.jsonl", ["pass"] * 100)
    h = write_labels(tmp_path / "h.jsonl", ["pass"] * 90 + ["fail"] * 10)

    code = main(["calibrate", j, h, "--seed", "0"])

    out = capsys.readouterr().out
    assert code == EXIT_UNTRUSTED
    assert "agreement   90.0%" in out
    assert "weights     none" in out
    assert "kappa       0.000" in out
    assert "judge bias" not in out
    assert "verdict     not trusted" in out


def test_calibrate_few_labels_is_inconclusive_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    human = [True, False, True, True, False, True, False, False, True, True]
    judge = list(human)
    judge[0] = False
    j = write_labels(tmp_path / "j.jsonl", judge)
    h = write_labels(tmp_path / "h.jsonl", human)

    code = main(["calibrate", j, h, "--seed", "0"])

    out = capsys.readouterr().out
    assert code == EXIT_UNTRUSTED
    assert "judge bias  -0.100  (stricter than humans)" in out
    assert "inconclusive, label more cases" in out


def test_calibrate_json_and_options(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    j = tmp_path / "j.jsonl"
    h = tmp_path / "h.jsonl"
    j.write_text('{"case": "a", "rating": 1}\n{"case": "b", "rating": 2}\n', encoding="utf-8")
    h.write_text('{"case": "a", "rating": 1}\n{"case": "b", "rating": 2}\n', encoding="utf-8")

    main(
        [
            "calibrate",
            str(j),
            str(h),
            "--id-key=case",
            "--label-key=rating",
            "--threshold=0.5",
            "--resamples=50",
            "--format=json",
        ]
    )

    data = json.loads(capsys.readouterr().out)
    assert data["kappa"] == 1.0
    assert data["threshold"] == 0.5
    assert data["n_resamples"] == 50
    assert data["judge_bias"] == 0.0


def test_calibrate_bad_labels_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    j = write_labels(tmp_path / "j.jsonl", ["good", "bad"])
    h = write_labels(tmp_path / "h.jsonl", ["good", "bad"])

    assert main(["calibrate", j, h, "--weights", "linear"]) == EXIT_USAGE
    assert "weighted kappa needs numeric labels" in capsys.readouterr().err
