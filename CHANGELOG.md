# Changelog

All notable changes to this project are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- **Breaking:** the `no_change` verdict is now `inconclusive`, in the CLI text and in JSON.
  An interval that contains zero means the data can't tell, not that nothing changed. If you
  parse `--format json`, look for `"inconclusive"` instead of `"no_change"`.
- An inconclusive comparison now says the largest drop the data can't rule out.

### Added

- `compare --margin`: the largest drop you accept. The result gets a decision of pass, fail
  or needs more evidence, kept apart from the verdict. Needs more evidence exits with the new
  code 3, so it fails a CI job.

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

[Unreleased]: https://github.com/dch2r/signalfloor/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/dch2r/signalfloor/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dch2r/signalfloor/releases/tag/v0.1.0
