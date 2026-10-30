# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.5.2] - 2026-10-29

The package itself only changes its description. The dashboard changes ship in the
repository, not on PyPI: pull and rebuild to get them.

### Changed

- The package description shows the margin workflow and every exit code, including 3 for
  needs more evidence.
- The dashboard labels its two answers "Change verdict" and "Release decision", with the
  margin, so an inconclusive verdict next to a pass reads as two separate questions.

### Fixed

- The dashboard drew the bootstrap interval on its axis while the verdict came from the
  bounds, so an inconclusive result could show a bar that cleared zero. The axis now draws the
  bounds, with the bootstrap interval inside them.

## [0.5.1] - 2026-10-29

### Fixed

- The betting interval stopped its search at 1e-9 and 1 - 1e-9, so data that was all 0 got
  an interval that left out 0, and a total drop of 1 passed a margin of 0.999999999. An end
  that can't be rejected is now reported exactly, and rounding only ever widens the interval.
- The server worked out the cases a margin needs on the event loop. For a tiny margin that
  took seconds and stalled every other request. The whole report now runs in a worker
  thread, and `cases_needed` and `no_change_drop` are cached.
- The agent's unit tests could reach the network. They now fail at once on any name lookup
  or connection, and the tests that did reach out stub the model server instead.

## [0.5.0] - 2026-10-29

Tagged but never published to PyPI. A review found the boundary issue fixed in 0.5.1
before it went out, so the two ship together as 0.5.1.

### Changed

- **Breaking:** verdicts and decisions now come from a confidence interval by betting
  (Waudby-Smith and Ramdas, 2024), which holds at any sample size for independent cases with
  scores in their range. 0.4.0 widened the bootstrap interval by the rule of three, but only
  past the most extreme differences seen, so once an eval held both a loss and a gain it fell
  back to the bootstrap: seven cases from a population where nothing changed failed 6.25% of
  the time. In that population the exact rate is now at most 0.8% for every eval of 1 to
  14 cases. The bounds are about half again as wide as the bootstrap interval, which is
  still shown.
- `cases_needed` is the count that passes a margin when nothing changed, not a minimum for
  every eval: a clear improvement passes with fewer. It returns None past a million cases.
  Margins of 0.02 and 0.05 need 249 and 98 cases.
- The JSON output and the API drop `unseen_share`, `min_diff` and `max_diff`, and add
  `no_change_drop`, the drop an eval this size can't rule out even when nothing changed.
- The validation study scores the 0.4.0 rule and the betting rule side by side, down to evals
  of 10 cases. On held-out questions the betting rule shipped at most 0.3% of bad changes and
  failed at most 0.3% of acceptable ones, and approved fewer acceptable changes than 0.4.0.

### Fixed

- The agent found no digest for the default embedding model, because Ollama lists
  `nomic-embed-text` as `nomic-embed-text:latest`. Names without a tag now mean `latest`.
- The agent treated a digest that was unknown when a run started as unchecked for good, so
  after one failed lookup any later digest was accepted. Digests now have to match exactly.

## [0.4.0] - 2026-10-29

Tagged but never published to PyPI. A review found its bounds could still fail an unchanged
eval of seven cases 6.25% of the time, and 0.5.0 replaces them.

### Changed

- **Breaking:** scores must lie in a stated range, 0 to 1 unless you pass `--score-range LOW
  HIGH` (`score_range` in the library, `score_low` and `score_high` in the API). 0.3.0
  guessed the range from the scores seen, so a sample where every score was 100.5 could pass
  any margin while the same sample at 0.5 could not.
- The verdict and the decision now come from bounds that widen the bootstrap interval on both
  sides, not only for passing. Two cases that both got worse used to give an interval of
  [-1, -1] and a fail. Drawn from an even population, that happened 25% of the time, and now
  0%. The bounds widen only past the lowest and highest difference the eval saw, so sparse
  results that already contain both extremes keep the plain bootstrap interval.
- The server and dashboard count cases that only one run has as missing. Each could be
  anything in the score range, so they widen the bounds. Before, a candidate that crashed on
  10 of 200 cases could pass a margin of 0.02 by leaving them out.
- The dashboard says "likely" instead of implying proof, and shows the bounds and any missing
  cases.

### Added

- `bound_low`, `bound_high`, `min_diff`, `max_diff` and `missing_cases` on comparisons, in the
  library, the JSON output and the API. The JSON output now also has
  `largest_drop_not_ruled_out`, which 0.3.0 left out.
- The validation study now reports approval, false failure, needs more evidence and unsafe
  approval side by side, for three kinds of damage and two margins, and checks the result on
  100 held-out questions from two new agent runs.

### Fixed

- `--margin 1e-20` no longer crashes with a ZeroDivisionError.

## [0.3.0] - 2026-10-29

### Changed

- **Breaking:** the `no_change` verdict is now `inconclusive`, in the CLI text and in JSON.
  An interval that contains zero means the data can't tell, not that nothing changed. If you
  parse `--format json`, look for `"inconclusive"` instead of `"no_change"`.
- An inconclusive comparison now says the largest drop the data can't rule out.
- `flaky` estimates the noise floor from the run means as well as from the cases, and uses the
  larger. The cases only estimate assumed cases vary independently, so it missed shifts that
  move a whole run, such as a model or judge change. The run estimate uses a Student t
  multiplier, so with few runs the band is wider. The output shows both and notes when runs
  move together or when there are too few runs.

- `calibrate` no longer trusts a judge on thin evidence. Every label the humans used needs at
  least 5 examples (`--min-per-label`), and the result is inconclusive when more than 5% of
  resamples leave kappa undefined. Before, two cases in perfect agreement came back trusted.
  The output lists the reasons.

### Added

- `calibrate` prints a confusion matrix of judge labels against human labels, and the JSON
  output includes it with the count of each human label.
- `compare --margin`: the largest drop you accept. The result gets a decision of pass, fail
  or needs more evidence, kept apart from the verdict. Needs more evidence exits with the new
  code 3, so it fails a CI job. Passing needs enough cases as well as a narrow interval: the
  largest drop not ruled out also counts cases the eval may have missed (the rule of three),
  and the output says how many cases the margin needs. Without this, a 20 case eval that drew
  none of the broken questions passed a real 3 point regression 30% of the time. See
  `studies/validation`.
- `cases_needed(margin)` in the library. `unseen_share` and `max_case_drop` in the JSON
  output and the API, and `cases_needed` in the API.
- A validation study in `studies/validation` that plants regressions into real agent results
  and compares signalfloor with a plain threshold on the mean.

### Fixed

- The GitHub Action adds an error annotation for needs more evidence, as it already did for a
  failed check.

## [0.2.0] - 2026-10-28

### Added

- GitHub Action. Add `uses: dch2r/signalfloor@<version>` to a workflow to run any command as a
  CI check. The result goes to the job summary and the step fails when the check fails.
- Example result files in `examples/` for trying the commands.

## [0.1.0] - 2026-10-27

First release.

### Added

- `signalfloor compare` compares two eval runs with a paired bootstrap and reports the change,
  a confidence interval and a verdict of regression, improvement or no detectable change.
- `signalfloor calibrate` measures how well an LLM judge agrees with human labels using
  Cohen's kappa, with optional linear or quadratic weights for ordered ratings. It reports
  judge bias and only trusts the judge when the whole confidence interval clears the threshold.
- `signalfloor flaky` finds cases whose scores move between identical runs and reports the
  noise floor and noise band of the suite.
- Results are read from JSON Lines files with configurable field names.
- Text and JSON output for every command.
- Exit code 1 when a check fails and 2 for bad input, so every command works as a CI check.

[Unreleased]: https://github.com/dch2r/signalfloor/compare/v0.5.2...HEAD
[0.5.2]: https://github.com/dch2r/signalfloor/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/dch2r/signalfloor/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/dch2r/signalfloor/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/dch2r/signalfloor/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/dch2r/signalfloor/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dch2r/signalfloor/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dch2r/signalfloor/releases/tag/v0.1.0
