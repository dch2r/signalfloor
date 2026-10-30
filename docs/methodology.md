# How signalfloor decides

This page explains the statistics behind each command and where each choice was tested. For
how to use the commands, see the [README](../README.md).

## compare

### Pairing

Each case is compared with itself: for every case id, the difference is candidate score minus
baseline score. Hard cases stay hard and easy cases stay easy in both runs, so pairing removes
most of the spread between cases from the comparison. On the test data in
`test_compare.py`, a drop of 0.02 that pairing finds on 300 cases is hidden when the two means
are compared on their own.

### Two intervals, and which one decides

The output shows two intervals for the mean difference.

- **The bootstrap interval** resamples the differences 10,000 times and takes the middle 95%
  of the resampled means. It is quick and familiar, and close to right on large evals. On
  small or lopsided evals it can be far off. If a change broke 4 of 100 questions, a 20
  question eval contains none of them 44% of the time, every difference is zero, and the
  interval is [0, 0]. An eval of 2 cases that both got worse gives [-1, -1].
- **The bounds** are a confidence interval by betting ([Waudby-Smith and Ramdas,
  2024](https://arxiv.org/abs/2010.09686)). For every candidate value of the mean, two
  bets are placed case by case, one that the data comes out above it and one below. A value
  that lets either bet grow its money past 1/alpha is ruled out. If the value is the true
  mean, neither bet can be expected to make money, so by Markov's inequality this happens
  with chance at most alpha. That argument holds at any sample size, for cases drawn
  independently with scores in a known range.

The verdict and the decision come only from the bounds. The bootstrap interval is shown for
reference.

Implementation details, in `_betting.py`:

- Bet sizes are the predictable plug-in from the paper, capped so a bet never risks more than
  75% of its money.
- The money depends on the order the cases are bet on. It is averaged over 20 orderings,
  which keeps the bounds steady and keeps them valid, since an average of values with
  expectation at most 1 also has expectation at most 1. The orderings are a fixed seeded
  shuffle of the order the cases were given in, so the same data always gives the same
  bounds. They are not sorted by value, which would break the independence the argument
  needs.
- The ends are found by bisection. An end that can't be ruled out, like 0 for data that is
  all 0, is reported exactly. Otherwise the reported end is on the ruled out side of the last
  step, so rounding can only widen the bounds.
- Because the money is averaged at the last case, the bounds are valid for the whole eval at
  once. They are not valid if you check them after every case and stop when you like.

The tests check the bounds by exact enumeration: every possible eval of 1 to 12 cases from
an even population (half the cases lose 1, half gain 1), from a sparse one, and from one where
4% of cases broke. The worst false fail rate in the even population is 0.78%, against 2.5%
allowed. The plain bootstrap failed 25% of two case evals and 6.25% of seven case evals.

The cost is width. On the reference agent's 100 question comparisons the bounds are about
half again as wide as the bootstrap interval.

### Score range

Scores must lie in a stated range, 0 to 1 unless set with `--score-range`. The bounds need to
know how far a case can move. The range is never guessed from the scores seen, because a
sample where every score is 100.5 says nothing about how far a score can fall.

### Verdict and decision

The verdict is `regression` when the upper bound is below zero, `improvement` when the lower
bound is above it, and `inconclusive` otherwise.

With `--margin m`, the decision is `fail` when the upper bound is below -m, `pass` when the
lower bound is at or above -m, and `needs more evidence` otherwise. The command reports the
cases an eval needs to pass the margin when nothing changed, which is when the bounds are at
their tightest:

| Margin | 0.01 | 0.02 | 0.03 | 0.05 | 0.10 |
|---|---:|---:|---:|---:|---:|
| Cases to pass an unchanged eval | 502 | 249 | 165 | 98 | 48 |

That is not a minimum for every eval. A clear improvement passes with fewer: 20 cases that
all went from 0 to 1 pass a margin of 0.02. Any losses mean more.

### Missing cases

The server can compare runs that don't share every case. Each case only one run has counts
as missing and could have scored anything in the range, so it widens the bounds by its share
of the suite. A candidate that crashed on 10 of 200 cases can't pass a margin of 0.02 by
leaving them out.

### Validation

The [validation study](../studies/validation) plants changes of known size into the
reference agent's real results, 180,000 trials over two sets of questions, and scores every
call. On held-out questions the rule "fail if the mean dropped by more than the margin"
shipped up to 48% of bad changes and failed up to 42% of good ones. The bounds kept both at
0.3% or less, and approved fewer good changes on small evals. The study has every rate.

## flaky

The noise band says how far the mean of a rerun with nothing changed is likely to land. It is
estimated two ways and the larger wins:

- **From the cases**: how much each case moves between runs, assuming cases move
  independently. Precise, but blind to anything that shifts many cases at once, like a model
  update or a judge change.
- **From the runs**: how much the run means themselves move, with a Student t multiplier for
  the small number of runs. This catches shared shifts but is rough with few runs.

In a simulation where every run shares a random shift, the cases only band held 71% of fresh
reruns instead of 95%, and the combined band held 97%. When cases really are independent the
combined band is about 1.3 times wider than it needs to be.

## calibrate

Agreement between judge and human labels is measured with Cohen's kappa, which removes the
agreement two raters would reach by chance. Its interval comes from a bootstrap over cases.
The judge is trusted only when the whole interval is above the threshold.

Every label the humans used needs at least 5 examples (`--min-per-label`), and the result is
inconclusive when more than 5% of resamples leave kappa undefined. Without those rules, two
cases in perfect agreement came back trusted, and in simulations a judge whose true kappa was
0.54, below a 0.6 threshold, was trusted up to 20% of the time when 10% of cases were
positive. With them, that stayed under 2% in every setting tried.
