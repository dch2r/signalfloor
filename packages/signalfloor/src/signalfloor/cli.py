"""Command line interface.

Exit codes:
    0  the check passed
    1  the check failed: a real regression for compare, a judge that is not proven
       trustworthy for calibrate
    2  bad input or usage
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence

from signalfloor import __version__
from signalfloor.calibration import Agreement, Trust, judge_agreement
from signalfloor.compare import Comparison, PairingError, Verdict, paired_bootstrap
from signalfloor.results import ResultsFileError, load_labels, load_scores

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_UNTRUSTED = 1
EXIT_USAGE = 2

_VERDICT_TEXT = {
    Verdict.REGRESSION: "regression",
    Verdict.IMPROVEMENT: "improvement",
    Verdict.NO_CHANGE: "no detectable change",
}

_TRUST_TEXT = {
    Trust.TRUSTED: "trusted",
    Trust.UNTRUSTED: "not trusted",
    Trust.INCONCLUSIVE: "inconclusive, label more cases",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (ResultsFileError, PairingError, ValueError) as e:
        print(f"signalfloor: error: {e}", file=sys.stderr)
        return EXIT_USAGE


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signalfloor",
        description="Find out if a drop in your LLM eval scores is real or just noise.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(title="commands", required=True)

    compare = commands.add_parser(
        "compare",
        help="compare two eval runs",
        description=(
            "Compare a candidate eval run against a baseline. Each file is JSON Lines with one "
            "test case per line. Exits with code 1 if the candidate is a real regression."
        ),
    )
    compare.add_argument("baseline", help="results file for the current version")
    compare.add_argument("candidate", help="results file for the new version")
    compare.add_argument(
        "--score-key", default="score", help="field holding the score (default: score)"
    )
    _add_common_options(compare)
    compare.set_defaults(handler=_run_compare)

    calibrate = commands.add_parser(
        "calibrate",
        help="check if an LLM judge agrees with human labels",
        description=(
            "Measure how well an LLM judge agrees with human labels on the same cases, using "
            "Cohen's kappa. Exits with code 1 unless the judge is proven trustworthy."
        ),
    )
    calibrate.add_argument("judge", help="labels from the LLM judge")
    calibrate.add_argument("human", help="labels from humans for the same cases")
    calibrate.add_argument(
        "--label-key", default="label", help="field holding the label (default: label)"
    )
    calibrate.add_argument(
        "--weights",
        choices=["linear", "quadratic"],
        help="give partial credit for close ratings, for ordered labels like 1 to 5",
    )
    calibrate.add_argument(
        "--threshold",
        type=float,
        default=0.6,
        help="minimum kappa to trust the judge (default: 0.6)",
    )
    _add_common_options(calibrate)
    calibrate.set_defaults(handler=_run_calibrate)

    return parser


def _add_common_options(command: argparse.ArgumentParser) -> None:
    command.add_argument("--id-key", default="id", help="field holding the case id (default: id)")
    command.add_argument(
        "--confidence", type=float, default=0.95, help="confidence level (default: 0.95)"
    )
    command.add_argument(
        "--resamples", type=int, default=10_000, help="bootstrap resamples (default: 10000)"
    )
    command.add_argument("--seed", type=int, help="random seed for repeatable results")
    command.add_argument(
        "--format", choices=["text", "json"], default="text", help="output format (default: text)"
    )


def _run_compare(args: argparse.Namespace) -> int:
    baseline = load_scores(args.baseline, id_key=args.id_key, score_key=args.score_key)
    candidate = load_scores(args.candidate, id_key=args.id_key, score_key=args.score_key)
    result = paired_bootstrap(
        baseline,
        candidate,
        confidence=args.confidence,
        n_resamples=args.resamples,
        seed=args.seed,
    )
    print(_to_json(result) if args.format == "json" else _format_compare(result))
    return EXIT_REGRESSION if result.verdict is Verdict.REGRESSION else EXIT_OK


def _run_calibrate(args: argparse.Namespace) -> int:
    judge = load_labels(args.judge, id_key=args.id_key, label_key=args.label_key)
    human = load_labels(args.human, id_key=args.id_key, label_key=args.label_key)
    result = judge_agreement(
        judge,
        human,
        weights=args.weights,
        threshold=args.threshold,
        confidence=args.confidence,
        n_resamples=args.resamples,
        seed=args.seed,
    )
    print(_to_json(result) if args.format == "json" else _format_calibrate(result))
    return EXIT_OK if result.verdict is Trust.TRUSTED else EXIT_UNTRUSTED


def _to_json(result: Comparison | Agreement) -> str:
    return json.dumps(dataclasses.asdict(result), indent=2)


def _format_compare(r: Comparison) -> str:
    level = f"{r.confidence:.0%}"
    return "\n".join(
        [
            f"cases       {r.n_cases}",
            f"baseline    {r.baseline_mean:.4f}",
            f"candidate   {r.candidate_mean:.4f}",
            f"change      {r.delta:+.4f}  ({level} CI {r.ci_low:+.4f} to {r.ci_high:+.4f})",
            "",
            f"verdict     {_VERDICT_TEXT[r.verdict]}",
        ]
    )


def _format_calibrate(r: Agreement) -> str:
    level = f"{r.confidence:.0%}"
    lines = [
        f"cases       {r.n_cases}",
        f"labels      {', '.join(str(c) for c in r.categories)}",
        f"weights     {r.weights or 'none'}",
        f"agreement   {r.raw_agreement:.1%}",
        f"kappa       {r.kappa:.3f}  ({level} CI {r.ci_low:.3f} to {r.ci_high:.3f})",
    ]
    if r.judge_bias is not None:
        lean = "more lenient" if r.judge_bias > 0 else "stricter" if r.judge_bias < 0 else "even"
        lines.append(f"judge bias  {r.judge_bias:+.3f}  ({lean} than humans)")
    lines += ["", f"verdict     {_TRUST_TEXT[r.verdict]} (threshold {r.threshold})"]
    return "\n".join(lines)
