# Contributing to ReviewPilot

Thanks for contributing to ReviewPilot.

## Before You Start

- Check existing issues and pull requests first so work does not overlap.
- Open an issue for bigger changes before you start coding.
- Keep changes small and focused. Small pull requests are easier to review and safer to merge.

## What To Contribute

Good contribution areas include:

- review quality improvements
- safer automation and learning flows
- documentation fixes
- install and release polish
- tests for real regressions

## Development Setup

1. Fork the repo and create a branch for your change.
2. Install the project dependencies you need for the area you are touching.
3. Make the smallest practical change that solves the problem.

## Validation

Run the checks that match your change before opening a pull request.

For most Python and workflow changes, that usually means:

```bash
pytest -q
ruff check .
mypy --strict $(git ls-files '*.py')
black --check $(git ls-files '*.py')
python3 scripts/validate_public_release.py
```

If your change only touches documentation, a smaller validation pass is fine.

## Pull Requests

When you open a pull request:

- explain what changed
- explain why it matters
- mention what you tested
- call out anything you did not test

If your change affects user-facing behavior, update the relevant docs in the same pull request.

## Review Guidelines

Please aim for:

- real bug fixes over style-only churn
- simple solutions over clever ones
- clear docs and examples
- tests for regressions when practical

## Security

Do not commit:

- secrets
- private tokens
- local machine paths that should not be public
- private review artifacts

If you find a security issue, please report it privately instead of opening a public issue with exploit details.
