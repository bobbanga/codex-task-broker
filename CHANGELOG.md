# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing has been released or tagged yet. Everything below describes the current
state of the `main` branch.

### Added

- `codex-broker validate` and `codex-broker run` for the mock-only protocol.
- Strict Run Request parsing that fails closed on unknown or missing fields.
- One bounded Contributor invocation using argv with `shell=false` and a
  filtered child environment.
- Independent recalculation of Git and verification evidence, written to a run
  store outside the target checkout, ending at `REVIEW_READY`.
- MIT license, contribution guide, code of conduct, security policy, and roadmap.
- Complete package metadata and project URLs for the public repository.
- Draft 2020-12 JSON Schema for the Run Request and a minimal example request.
- Windows GitHub Actions CI for Python 3.11 and 3.12 with lint, tests, and a
  build/install/help smoke test.
