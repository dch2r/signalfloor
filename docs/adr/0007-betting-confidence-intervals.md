# ADR 0007: Decide from a confidence interval by betting

- Status: Accepted
- Date: 2026-10-29

## Context

`compare` first decided from a paired percentile bootstrap. That interval only approaches its
stated coverage as the sample grows. Three failures turned up, each with a test now:

- An eval that drew none of the cases a change broke had every difference at zero and an
  interval of [0, 0], so it passed any margin. In the validation study this shipped up to 40%
  of real regressions on small evals.
- Two cases that both got worse gave [-1, -1], so an unchanged population failed 25% of two
  case evals.
- A patch that widened the bootstrap by the rule of three, but only past the extremes seen,
  fell back to the bootstrap whenever an eval held both a loss and a gain. Seven cases from an
  unchanged population failed 6.25% of the time.

Each patch fixed one case and left the next. The method needed a guarantee, not more patches.

## Decision

Make every verdict and decision from a confidence interval by betting (Waudby-Smith and
Ramdas, JRSS-B 2024), which is valid at any sample size for independent cases with scores in a
known range. Keep the bootstrap interval in the output as a quick estimate, with no call made
from it. Average the betting wealth over 20 fixed-seed orderings of the given case order, so
the result is stable and repeatable. Require the score range instead of inferring it.

## Consequences

- The tests can check coverage exactly, by enumerating every eval of up to 12 cases, instead
  of by sampling.
- The bounds are about half again as wide as the bootstrap interval. On the reference agent's
  100 question comparisons, the prompt change that the bootstrap calls an improvement is
  inconclusive under the bounds.
- Small evals mostly get "needs more evidence". In the validation study, at margin 0.05, the
  bounds approved 24% of acceptable changes at 100 cases and 47% at 200.
- The guarantee covers the whole eval at once. It does not cover checking after every case
  and stopping early.
