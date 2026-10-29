import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from signalfloor.cli import (
    EXIT_NEEDS_MORE_EVIDENCE,
    EXIT_OK,
    EXIT_REGRESSION,
    EXIT_TOO_FLAKY,
    EXIT_UNTRUSTED,
    EXIT_USAGE,
    main,
)


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


def test_inconclusive_exits_with_code_0_and_says_what_it_cannot_rule_out(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = write_run(tmp_path / "b.jsonl", [0.5] * 8)
    noisy = write_run(tmp_path / "n.jsonl", [0.8, 0.2] * 4)

    code = main(["compare", base, noisy, "--seed", "0"])

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert "verdict     inconclusive" in out
    assert "the data can't rule out a drop of up to 0.2" in out
    assert "set --margin" in out


@pytest.mark.parametrize(
    ("candidate", "margin", "code", "decision"),
    [
        ("same", "0.02", EXIT_OK, "pass"),
        ("better", "0", EXIT_OK, "pass"),
        ("worse", "0.05", EXIT_REGRESSION, "fail"),
        # A drop of exactly 0.2 is shown, which a margin of 0.5 allows.
        ("worse", "0.5", EXIT_OK, "pass"),
    ],
)
def test_margin_decisions(
    runs: dict[str, str],
    capsys: pytest.CaptureFixture[str],
    candidate: str,
    margin: str,
    code: int,
    decision: str,
) -> None:
    result = main(["compare", runs["base"], runs[candidate], "--seed", "0", "--margin", margin])

    assert result == code
    assert f"decision    {decision} (margin {float(margin):g})" in capsys.readouterr().out


def test_margin_needs_more_evidence_when_the_interval_straddles_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = write_run(tmp_path / "b.jsonl", [0.5] * 8)
    noisy = write_run(tmp_path / "n.jsonl", [0.8, 0.2] * 4)

    code = main(["compare", base, noisy, "--seed", "0", "--margin", "0.05"])

    assert code == EXIT_NEEDS_MORE_EVIDENCE
    assert "decision    needs more evidence (margin 0.05)" in capsys.readouterr().out


def test_margin_in_json(runs: dict[str, str], capsys: pytest.CaptureFixture[str]) -> None:
    main(["compare", runs["base"], runs["same"], "--margin", "0.02", "--format", "json"])

    result = json.loads(capsys.readouterr().out)
    assert (result["margin"], result["decision"]) == (0.02, "pass")


def test_negative_margin_is_a_usage_error(
    runs: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["compare", runs["base"], runs["same"], "--margin", "-0.1"]) == EXIT_USAGE
    assert "margin must be zero or more" in capsys.readouterr().err


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


def test_flaky_lists_cases_and_noise(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stable = [1.0] * 18
    paths = [
        write_run(tmp_path / "r1.jsonl", [*stable, 1.0, 0.0]),
        write_run(tmp_path / "r2.jsonl", [*stable, 0.0, 0.0]),
        write_run(tmp_path / "r3.jsonl", [*stable, 1.0, 1.0]),
    ]

    code = main(["flaky", *paths])

    out = capsys.readouterr().out
    assert code == EXIT_TOO_FLAKY
    assert "runs        3" in out
    assert "cases       20" in out
    assert "run means   0.9500, 0.9000, 1.0000" in out
    assert "noise band  +/-" in out
    assert "flaky       2 of 20 cases (10.0%)" in out
    assert "case-18  1.000   1 0 1" in out
    assert "case-19  1.000   0 0 1" in out


def test_flaky_under_max_rate_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = write_run(tmp_path / "a.jsonl", [1.0] * 9 + [1.0])
    b = write_run(tmp_path / "b.jsonl", [1.0] * 9 + [0.0])

    assert main(["flaky", a, b, "--max-flaky-rate", "0.1"]) == EXIT_OK
    assert main(["flaky", a, b, "--max-flaky-rate", "0.05"]) == EXIT_TOO_FLAKY


def test_flaky_with_no_flaky_cases(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = write_run(tmp_path / "a.jsonl", [0.5, 0.8])

    assert main(["flaky", a, a]) == EXIT_OK
    out = capsys.readouterr().out
    assert "flaky       0 of 2 cases (0.0%)" in out
    assert "spread" not in out


def test_flaky_top_limits_the_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = write_run(tmp_path / "a.jsonl", [0.0] * 5)
    b = write_run(tmp_path / "b.jsonl", [0.5, 0.4, 0.3, 0.2, 0.1])

    main(["flaky", a, b, "--top", "2"])

    out = capsys.readouterr().out
    assert "case-0  0.500" in out
    assert "case-1  0.400" in out
    assert "case-2" not in out
    assert "... and 3 more, use --top to see them" in out


def test_flaky_tolerance_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    a = write_run(tmp_path / "a.jsonl", [0.80, 0.50])
    b = write_run(tmp_path / "b.jsonl", [0.85, 0.10])

    main(["flaky", a, b, "--tolerance", "0.1", "--format", "json"])

    data = json.loads(capsys.readouterr().out)
    assert data["tolerance"] == 0.1
    assert [f["case_id"] for f in data["flaky"]] == ["case-1"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [([], "at least 2 runs"), (["--max-flaky-rate", "1.5"], "--max-flaky-rate")],
)
def test_flaky_bad_input_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str], message: str
) -> None:
    a = write_run(tmp_path / "a.jsonl", [1.0, 0.0])
    paths = [a] if not extra else [a, a]

    assert main(["flaky", *paths, *extra]) == EXIT_USAGE
    assert message in capsys.readouterr().err


def test_flaky_notes_shared_movement_and_few_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = [write_run(tmp_path / f"r{r}.jsonl", [float(r % 2)] * 50) for r in range(4)]

    main(["flaky", *paths, "--max-flaky-rate", "1"])

    out = capsys.readouterr().out
    assert "from cases +/-" in out and "from runs +/-" in out
    assert "whole runs move together" in out
    assert "with 4 runs the estimate from runs is rough" in out


def test_flaky_has_no_notes_with_many_steady_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scores = [0.5, 0.6, 0.7, 0.8] * 10
    paths = [write_run(tmp_path / f"r{r}.jsonl", scores) for r in range(5)]

    main(["flaky", *paths])

    assert "note" not in capsys.readouterr().out


def test_calibrate_shows_the_confusion_matrix_and_why_it_is_unsure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    labels = tmp_path / "l.jsonl"
    labels.write_text('{"id": "a", "label": 0}\n{"id": "b", "label": 1}\n', encoding="utf-8")

    code = main(["calibrate", str(labels), str(labels), "--seed", "0"])

    out = capsys.readouterr().out
    assert code == EXIT_UNTRUSTED
    assert "judge \\ human" in out
    assert "why         humans gave label 0 to only 1 case, need at least 5" in out


def test_calibrate_min_per_label_option(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    labels = tmp_path / "l.jsonl"
    lines = [json.dumps({"id": f"c{i}", "label": i % 2}) for i in range(8)]
    labels.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert main(["calibrate", str(labels), str(labels), "--seed", "0"]) == EXIT_UNTRUSTED
    capsys.readouterr()
    assert (
        main(["calibrate", str(labels), str(labels), "--seed", "0", "--min-per-label", "4"])
        == EXIT_OK
    )
