# Examples

Every subfolder is a fully-working, copy-paste starting point. Pick the one
that matches your cloud:

| Path                         | Trigger                | When to use                            |
| ---------------------------- | ---------------------- | -------------------------------------- |
| [`gcp-cloud-function/`](gcp-cloud-function/)   | GCP Pub/Sub            | Recommended for GCP billing & monitoring |
| [`aws-lambda/`](aws-lambda/)               | AWS SNS                | Recommended for AWS budgets & CloudWatch |
| [`local-dev/`](local-dev/)                | HTTP (FastAPI)         | Local iteration; never production        |
| [`payloads/`](payloads/)                 | —                      | Canonical sample events for curl & tests |

All three deployment examples share the exact same pattern:

1. A tiny wrapper file (~10 lines) that imports `cloud_alert_hub` and calls one
   function.
2. A `requirements.txt` that installs `cloud_alert_hub` from your public GitHub
   repo (`pip install git+https://github.com/...`).
3. A `config.yaml` that turns on just the features this deployment should
   handle.

That means the GitHub codebase stays untouched per deployment — you only ship
a different `config.yaml`.
