# Contributing to `cloud-alert-hub`

Thanks for taking the time to contribute! This project is small on purpose,
which means every change has a big impact — please read this guide before
opening a PR so your contribution lands cleanly.

---

## Ways to contribute

- **Report bugs** — open an issue with a minimal reproduction (payload +
  config + observed vs. expected behavior).
- **Suggest features** — propose a new built-in feature (`kind == "..."`),
  a new notifier, or a new cloud adapter.
- **Improve docs** — typos, clearer examples, better diagrams. Docs-only PRs
  are always welcome.
- **Code** — fix a bug, add a feature, or refactor internals. See
  [development workflow](#development-workflow).

Before starting non-trivial work, open a short issue describing what you're
planning. That saves everyone from duplicated effort.

---

## Code of conduct

Participation is governed by the
[Contributor Covenant-style Code of Conduct](CODE_OF_CONDUCT.md). Be kind,
assume good intent, and keep the discussion focused on code and design.

---

## Development workflow

### 1. Fork and clone

```bash
git clone https://github.com/<Tarunrj99>/cloud-alert-hub.git
cd cloud-alert-hub
```

### 2. Create a virtualenv and install in editable mode

```bash
make venv            # python -m venv .venv
source .venv/bin/activate
make install         # pip install -e ".[dev]"
```

Or without the Makefile:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Run the checks locally

```bash
make test            # pytest
make lint            # ruff check .
```

Both must be green before you push.

### 4. Optional: run the local dev server

```bash
make run-server
# in another shell
curl -sX POST http://127.0.0.1:8000/ingest/generic \
  -H 'content-type: application/json' \
  -d @examples/payloads/generic-budget-alert.json | jq
```

---

## Branching and PRs

- Work on a **feature branch**, never on `main`.
- Branch name convention: `feat/<short-desc>`, `fix/<short-desc>`,
  `docs/<short-desc>`, `refactor/<short-desc>`.
- Keep PRs **focused and small**. One logical change per PR.
- Rebase onto the latest `main` before marking the PR ready.
- Link the PR to an issue if one exists (`Fixes #12`).

### PR checklist

- [ ] Tests added or updated under `tests/`
- [ ] `make test` passes
- [ ] `make lint` passes
- [ ] Public behavior change? Updated `docs/` and `README.md`
- [ ] New config key? Updated `src/cloud_alert_hub/bundled_defaults.yaml`,
      `config.example.yaml`, and `docs/CONFIGURATION.md`
- [ ] New feature? Entry added to `docs/FEATURES.md` and `docs/SCENARIOS.md`
- [ ] Added a bullet to `CHANGELOG.md` under `## [Unreleased]`

A PR template is prefilled automatically when you open a PR on GitHub.

---

## Commit style

Write commit messages in the imperative mood, with an optional scope prefix:

```
feat(features): add cost_anomaly feature
fix(renderer): escape Slack special chars in labels
docs: clarify GCP IAM prerequisites in DEPLOY_GCP.md
refactor(policy): extract dedupe key builder
test(api): add end-to-end test for handle_aws_sns
```

Prefixes in use: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`.

Keep the subject ≤ 72 characters. Add a body for anything non-obvious:
_why_ the change matters, edge cases, deliberate trade-offs.

---

## Adding a new feature

A feature is a single file in `src/cloud_alert_hub/features/`. To add one:

1. Create `src/cloud_alert_hub/features/my_feature.py` with a class that extends
   `Feature` and implements `claims()` + `match()`. See
   [`budget.py`](src/cloud_alert_hub/features/budget.py) as the reference.
2. Register it in `src/cloud_alert_hub/features/__init__.py` by appending the
   class to `FEATURE_CLASSES`.
3. Add a default block to `src/cloud_alert_hub/bundled_defaults.yaml`:

   ```yaml
   features:
     my_feature:
       enabled: false
       dedupe_window_seconds: 300
       route: default
   ```

4. Mirror the block in `config.example.yaml` with inline comments.
5. Document the feature in `docs/FEATURES.md` and, if it's a distinct
   scenario, in `docs/SCENARIOS.md`.
6. Add a unit test in `tests/test_features.py` covering `claims()` and
   `match()` for a representative payload.

That's it — existing deployments keep working because the feature is off by
default. New deployments opt in by setting
`features.my_feature.enabled: true`.

---

## Adding a new cloud adapter

1. Create `src/cloud_alert_hub/adapters/your_cloud.py` that exposes
   `from_your_cloud(payload: dict) -> CanonicalAlert`.
2. Re-export it from `src/cloud_alert_hub/adapters/__init__.py`.
3. Add a convenience `handle_your_cloud(...)` in `src/cloud_alert_hub/api.py`
   that wires the adapter to the shared pipeline.
4. Copy one of the `examples/` folders (e.g. `examples/gcp-cloud-function/`)
   into `examples/your-cloud-runtime/` and adjust the wrapper + `deploy.sh`.
5. Add a unit test parsing a real, anonymised payload.

---

## Adding a new notifier

1. Add `src/cloud_alert_hub/notifiers/my_notifier.py` exposing a `send(...)`
   function with the same signature shape as `slack.py` / `email.py`.
2. Wire it into `src/cloud_alert_hub/processor.py` behind a config gate
   (`notifications.my_notifier.enabled`).
3. Extend `config.example.yaml` and `bundled_defaults.yaml`.
4. Document it in `docs/CONFIGURATION.md`.

---

## Testing conventions

- Use `pytest` style functions — no `unittest.TestCase`.
- Tests are named `test_<module>.py` and live under `tests/`.
- Prefer **fixtures** over globals for sample payloads.
- One assertion concept per test. Multiple `assert`s are fine if they
  describe the same behavior.
- External HTTP calls are **never** made in tests; mock `httpx` or inject a
  fake notifier.

Run a single test:

```bash
pytest tests/test_features.py::test_budget_feature_matches_budget_alerts -q
```

---

## Documentation conventions

- Markdown only. Keep lines under ~100 chars where it helps diff review.
- Use **relative** links so they render correctly on GitHub. From the repo
  root, link to docs as `docs/FEATURES.md`; from inside the `docs/` folder,
  link back to the root as `../README.md`.
- Update the doc index in `README.md` when adding a new doc file.
- Inline code: backticks. File paths: backticks. Commands: fenced code
  blocks with the shell hint (` ```bash`).

---

## Release process (maintainers)

1. Update `version` in `pyproject.toml`.
2. Move entries from `## [Unreleased]` to a new version section in
   `CHANGELOG.md`.
3. Commit: `chore(release): v0.y.z`.
4. Tag: `git tag v0.y.z && git push --tags`.
5. Downstream deployments pick it up by bumping the tag in their
   `requirements.txt`.

---

## Questions?

Open a [discussion](https://github.com/Tarunrj99/cloud-alert-hub/discussions)
or an issue. We'll be happy to help.
