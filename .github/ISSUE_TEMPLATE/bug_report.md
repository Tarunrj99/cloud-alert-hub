---
name: Bug report
about: Something isn't working as documented
title: "[bug] "
labels: ["bug"]
assignees: []
---

## What happened

<!-- A clear, short description of the bug. -->

## What you expected

<!-- What should have happened instead? -->

## Reproduction

Minimum config snippet:

```yaml
# your config.yaml excerpt
```

Minimum payload:

```json
{ "kind": "...", "title": "...", "summary": "..." }
```

Exact command or wrapper invocation:

```bash
# e.g. curl -sX POST http://127.0.0.1:8000/ingest/generic -d @payload.json
```

## Environment

- `cloud-alert-hub` version / commit:
- Python version: `python --version`
- OS:
- Deployment target (GCP Cloud Function / AWS Lambda / local / other):

## Logs

<details>
<summary>Log output</summary>

```
paste log output here
```

</details>

## Additional context

<!-- Anything else that might help — screenshots of Slack output, related PRs, etc. -->
