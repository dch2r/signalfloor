"""Command line interface.

Exit codes:
    0  no regression found
    1  the candidate is a real regression
    2  bad input or usage
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence

from signalfloor import __version__
from signalfloor.compare import Comparison, PairingError, Verdict, paired_bootstrap
from signalfloor.results import ResultsFileError, load_scores

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_USAGE = 2

_VERDICT_TEXT = {
    Verdict.REGRESSION: "regression",
    Verdict.IMPROVEMENT: "improvement",
    Verdict.NO_CHANGE: "no detectable change",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


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
    compare.add_argument("--id-key", default="id", help="field holding the case id (default: id)")
    compare.add_argument(
        "--score-key", default="score", help="field holding the score (default: score)"
    )
    compare.add_argument(
        "--confidence", type=float, default=0.95, help="confidence level (default: 0.95)"
    )
    compare.add_argument(
        "--resamples", type=int, default=10_000, help="bootstrap resamples (default: 10000)"
    )
    compare.add_argument("--seed", type=int, help="random seed for repeatable results")
    compare.add_argument(
        "--format", choices=["text", "json"], default="text", help="output format (default: text)"
    )
    compare.set_defaults(handler=_run_compare)
    return parser


def _run_compare(args: argparse.Namespace) -> int:
    try:
        baseline = load_scores(args.baseline, id_key=args.id_key, score_key=args.score_key)
        candidate = load_scores(args.candidate, id_key=args.id_key, score_key=args.score_key)
        result = paired_bootstrap(
            baseline,
            candidate,
            confidence=args.confidence,
            n_resamples=args.resamples,
            seed=args.seed,
        )
    except (ResultsFileError, PairingError, ValueError) as e:
        print(f"signalfloor: error: {e}", file=sys.stderr)
        return EXIT_USAGE

    if args.format == "json":
        print(json.dumps(dataclasses.asdict(result), indent=2))
    else:
        print(_format_text(result))

    return EXIT_REGRESSION if result.verdict is Verdict.REGRESSION else EXIT_OK


def _format_text(r: Comparison) -> str:
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
