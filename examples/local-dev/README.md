# Local dev server

A FastAPI app that mounts the same public API the Cloud Function / Lambda use,
plus debug endpoints. Meant for development — **not** a production deployment
target.

## Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[server]"             # from the repo root
uvicorn examples.local-dev.app:app --reload
```

## Try it

```bash
# Dry-run (no Slack credentials needed)
curl -sX POST http://127.0.0.1:8000/ingest/generic \
  -H 'content-type: application/json' \
  -d @examples/payloads/generic-budget-alert.json | jq

# See live config & metrics
curl -s http://127.0.0.1:8000/debug/config | jq
curl -s http://127.0.0.1:8000/debug/metrics | jq
```

## Point at a different config

```bash
CLOUD_ALERT_HUB_CONFIG=/path/to/my-override.yaml uvicorn examples.local-dev.app:app --reload
```
