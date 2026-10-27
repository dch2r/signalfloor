# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/dch2r/signalfloor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/dch2r/signalfloor/releases/tag/v0.1.0
