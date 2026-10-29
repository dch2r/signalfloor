"""Command line interface.

Exit codes:
    0  the check passed
    1  the check failed: a real regression for compare (or a drop past --margin), a judge
       that is not proven trustworthy for calibrate, too many flaky cases for flaky
    2  bad input or usage
    3  compare with --margin only: the data can't tell if the drop is within the margin
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence

from signalfloor import __version__
from signalfloor.calibration import Agreement, Trust, judge_agreement
from signalfloor.compare import (
    Comparison,
    Decision,
    PairingError,
    Verdict,
    cases_needed,
    paired_bootstrap,
)
from signalfloor.results import ResultsFileError, load_labels, load_scores
from signalfloor.stability import FEW_RUNS, Stability, find_flaky

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_UNTRUSTED = 1
EXIT_TOO_FLAKY = 1
EXIT_USAGE = 2
EXIT_NEEDS_MORE_EVIDENCE = 3

_VERDICT_TEXT = {
    Verdict.REGRESSION: "regression",
    Verdict.IMPROVEMENT: "improvement",
    Verdict.INCONCLUSIVE: "inconclusive",
}

_DECISION_TEXT = {
    Decision.PASS: "pass",
    Decision.FAIL: "fail",
    Decision.NEEDS_MORE_EVIDENCE: "needs more evidence",
}

_DECISION_EXIT = {
    Decision.PASS: EXIT_OK,
    Decision.FAIL: EXIT_REGRESSION,
    Decision.NEEDS_MORE_EVIDENCE: EXIT_NEEDS_MORE_EVIDENCE,
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
            "test case per line. Exits with code 1 if the candidate is a real regression. With "
            "--margin, exits 0 only if any drop is shown to be within the margin, 1 if it is "
            "shown to be larger, and 3 if the data can't tell."
        ),
    )
    compare.add_argument("baseline", help="results file for the current version")
    compare.add_argument("candidate", help="results file for the new version")
    compare.add_argument(
        "--score-key", default="score", help="field holding the score (default: score)"
    )
    compare.add_argument(
        "--margin",
        type=float,
        help="the largest drop in mean score you will accept, such as 0.02",
    )
    compare.add_argument(
        "--score-range",
        nargs=2,
        type=float,
        metavar=("LOW", "HIGH"),
        default=(0.0, 1.0),
        help="the lowest and highest score your metric can give (default: 0 1)",
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
    calibrate.add_argument(
        "--min-per-label",
        type=int,
        default=5,
        help="human examples each label needs before the judge can be trusted (default: 5)",
    )
    _add_common_options(calibrate)
    calibrate.set_defaults(handler=_run_calibrate)

    flaky = commands.add_parser(
        "flaky",
        help="find flaky cases across repeated runs",
        description=(
            "Compare several runs of the same eval with nothing changed. Lists the cases whose "
            "scores move between runs and reports the noise floor of the suite. Exits with "
            "code 1 if the share of flaky cases is above --max-flaky-rate."
        ),
    )
    flaky.add_argument("runs", nargs="+", help="results files from repeated runs, at least 2")
    flaky.add_argument(
        "--score-key", default="score", help="field holding the score (default: score)"
    )
    flaky.add_argument(
        "--tolerance",
        type=float,
        default=0.0,
        help="how far a score may move before the case counts as flaky (default: 0)",
    )
    flaky.add_argument(
        "--max-flaky-rate",
        type=float,
        default=0.05,
        help="share of flaky cases allowed before the check fails (default: 0.05)",
    )
    flaky.add_argument(
        "--top", type=int, default=10, help="how many flaky cases to list (default: 10)"
    )
    _add_common_options(flaky, bootstrap=False)
    flaky.set_defaults(handler=_run_flaky)

    return parser


def _add_common_options(command: argparse.ArgumentParser, *, bootstrap: bool = True) -> None:
    command.add_argument("--id-key", default="id", help="field holding the case id (default: id)")
    command.add_argument(
        "--confidence", type=float, default=0.95, help="confidence level (default: 0.95)"
    )
    if bootstrap:
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
        margin=args.margin,
        score_range=tuple(args.score_range),
    )
    print(_to_json(result) if args.format == "json" else _format_compare(result))
    if result.decision is not None:
        return _DECISION_EXIT[result.decision]
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
        min_per_label=args.min_per_label,
    )
    print(_to_json(result) if args.format == "json" else _format_calibrate(result))
    return EXIT_OK if result.verdict is Trust.TRUSTED else EXIT_UNTRUSTED


def _run_flaky(args: argparse.Namespace) -> int:
    if not 0 <= args.max_flaky_rate <= 1:
        raise ValueError(f"--max-flaky-rate must be between 0 and 1, got {args.max_flaky_rate}")
    runs = [load_scores(p, id_key=args.id_key, score_key=args.score_key) for p in args.runs]
    result = find_flaky(runs, tolerance=args.tolerance, confidence=args.confidence)
    print(_to_json(result) if args.format == "json" else _format_flaky(result, args.top))
    return EXIT_TOO_FLAKY if result.flaky_rate > args.max_flaky_rate else EXIT_OK


def _to_json(result: Comparison | Agreement | Stability) -> str:
    data = dataclasses.asdict(result)
    if isinstance(result, Comparison):
        # Properties, which asdict leaves out.
        data["bound_low"] = result.bound_low
        data["bound_high"] = result.bound_high
        data["largest_drop_not_ruled_out"] = result.largest_drop_not_ruled_out
    return json.dumps(data, indent=2)


def _format_compare(r: Comparison) -> str:
    level = f"{r.confidence:.0%}"
    lines = [
        f"cases       {r.n_cases}",
        f"baseline    {r.baseline_mean:.4f}",
        f"candidate   {r.candidate_mean:.4f}",
        f"change      {r.delta:+.4f}  ({level} CI {r.ci_low:+.4f} to {r.ci_high:+.4f})",
        f"bounds      {r.bound_low:+.4f} to {r.bound_high:+.4f}  "
        "(the interval widened for cases the eval may have missed)",
        "",
        f"verdict     {_VERDICT_TEXT[r.verdict]}",
    ]
    drop = r.largest_drop_not_ruled_out
    if r.verdict is Verdict.INCONCLUSIVE:
        lines.append(f"            the data can't rule out a drop of up to {drop:.4f}")
    if r.decision is not None and r.margin is not None:
        lines.append(f"decision    {_DECISION_TEXT[r.decision]} (margin {r.margin:g})")
        unseen = r.unseen_share * r.max_case_drop
        if r.decision is Decision.NEEDS_MORE_EVIDENCE and unseen > r.margin:
            lines += [
                f"            {r.n_cases} cases can't rule out a drop of {unseen:.4f} even if "
                "nothing changed:",
                f"            a change that broke {r.unseen_share:.1%} of cases could miss "
                "every one of them",
            ]
            if r.margin > 0:
                needed = cases_needed(
                    r.margin, confidence=r.confidence, max_case_drop=r.max_case_drop
                )
                lines.append(f"            a margin of {r.margin:g} needs at least {needed} cases")
    elif r.verdict is Verdict.INCONCLUSIVE:
        lines.append("            set --margin to the largest drop you accept to get a decision")
    return "\n".join(lines)


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
    lines += ["", *_confusion_table(r), ""]
    lines.append(f"verdict     {_TRUST_TEXT[r.verdict]} (threshold {r.threshold})")
    lines += [f"why         {reason}" for reason in r.reasons]
    return "\n".join(lines)


def _confusion_table(r: Agreement) -> list[str]:
    # Which labels the judge gets wrong, not just how often. Rows are the judge's labels.
    names = [str(c) for c in r.categories]
    width = max(5, *(len(n) for n in names)) + 2
    header = "judge \\ human".ljust(14) + "".join(n.rjust(width) for n in names)
    rows = [
        f"  {name}".ljust(14) + "".join(str(x).rjust(width) for x in row)
        for name, row in zip(names, r.confusion, strict=True)
    ]
    return [header, *rows]


def _format_flaky(r: Stability, top: int) -> str:
    level = f"{r.confidence:.0%}"
    lines = [
        f"runs        {r.n_runs}",
        f"cases       {r.n_cases}",
        f"run means   {', '.join(f'{m:.4f}' for m in r.run_means)}",
        f"noise floor {r.noise_floor:.4f}",
        f"noise band  +/-{r.noise_band:.4f}  ({level} of reruns stay within this)",
        f"            from cases +/-{r.noise_band_cases:.4f}, from runs +/-{r.noise_band_runs:.4f}",
        f"flaky       {len(r.flaky)} of {r.n_cases} cases ({r.flaky_rate:.1%})",
    ]
    # Runs moving together more than independent cases can explain point at something shared.
    if r.noise_floor_runs > 2 * r.noise_floor_cases:
        lines.append(
            "note        whole runs move together more than their cases explain. Something "
            "shared, like the model, the judge or the infrastructure, changes between runs."
        )
    if r.n_runs < FEW_RUNS:
        lines.append(
            f"note        with {r.n_runs} runs the estimate from runs is rough. "
            f"{FEW_RUNS} or more make it reliable."
        )
    if r.flaky:
        shown = r.flaky[:top]
        width = max(len(f.case_id) for f in shown)
        lines += ["", f"{'case':<{width}}  spread  scores"]
        for f in shown:
            scores = " ".join(f"{s:g}" for s in f.scores)
            lines.append(f"{f.case_id:<{width}}  {f.spread:<6.3f}  {scores}")
        if len(r.flaky) > len(shown):
            lines.append(f"... and {len(r.flaky) - len(shown)} more, use --top to see them")
    return "\n".join(lines)
