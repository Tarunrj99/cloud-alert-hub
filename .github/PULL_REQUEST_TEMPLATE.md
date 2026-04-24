<!--
Thanks for the PR! Please fill in the sections below so reviewers have the
context they need. Items not relevant to your change can be deleted.
-->

## Summary

<!-- What does this PR do? One or two sentences. -->

## Motivation

<!-- Why is this change worth making? Link the issue if one exists: Fixes #123 -->

## Changes

<!-- Bullet list of the main changes. -->

-
-

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to change)
- [ ] Documentation update
- [ ] Refactor / internal cleanup

## Testing

<!-- How did you verify the change? Commands run, payloads used, screenshots of Slack output, etc. -->

```bash
make test
make lint
```

## Checklist

- [ ] `make test` passes locally
- [ ] `make lint` passes locally
- [ ] New/changed public behavior is documented (`README.md` / `docs/`)
- [ ] New config key? Updated `bundled_defaults.yaml`, `config.example.yaml`, and `docs/CONFIGURATION.md`
- [ ] New feature? Added to `docs/FEATURES.md` and `docs/SCENARIOS.md`
- [ ] Added an entry under `## [Unreleased]` in `CHANGELOG.md`
- [ ] No secrets or customer data in tests, commits, or fixtures
