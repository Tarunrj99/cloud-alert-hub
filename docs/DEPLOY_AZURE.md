# Deploying on Azure

The recommended runtime is an **Event Grid–triggered Azure Function** (Python
worker). The library ships an `azure_blob` state backend so dedup state
survives function-app cold starts; cloud-native, no new managed service
beyond the Storage Account every Function App already has.

> Azure isn't yet covered by a turnkey example folder — the library and its
> adapters work, this guide explains how to wire it up.

## Prerequisites

| Item | How to check / fix |
| ---- | ------------------ |
| Azure CLI v2 installed and logged in | `az account show` |
| Subscription you can deploy to | `az account list -o table` |
| Resource group | `az group create -n alert-hub-rg -l eastus` |
| Function App + Storage Account | created in step 1 below |
| Slack incoming webhook URL | <https://api.slack.com/messaging/webhooks> |

## 1. Create the Function App and Storage Account (one-time)

Every Azure Function App requires a Storage Account for its own runtime.
We re-use that same account for the dedup state — no extra service.

```bash
export RG=alert-hub-rg
export LOC=eastus
export STG="alerthub$RANDOM"          # globally unique, lowercase
export FUNCAPP="alert-hub-func-$RANDOM"

az group create -n "$RG" -l "$LOC"

az storage account create \
  --name "$STG" --resource-group "$RG" --location "$LOC" \
  --sku Standard_LRS --kind StorageV2

az functionapp create \
  --name "$FUNCAPP" --resource-group "$RG" \
  --storage-account "$STG" --consumption-plan-location "$LOC" \
  --runtime python --runtime-version 3.11 --functions-version 4

# Container that the dedup state blob will live in
az storage container create \
  --name alert-hub-state --account-name "$STG"
```

## 2. Grant the Function App access to the dedup container

We use **system-assigned managed identity** (no secrets in env vars):

```bash
# Turn on the system-assigned identity
az functionapp identity assign --name "$FUNCAPP" --resource-group "$RG"

PRINCIPAL_ID=$(az functionapp identity show \
  --name "$FUNCAPP" --resource-group "$RG" --query principalId -o tsv)

STG_ID=$(az storage account show \
  --name "$STG" --resource-group "$RG" --query id -o tsv)

az role assignment create \
  --assignee-object-id "$PRINCIPAL_ID" \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope "${STG_ID}/blobServices/default/containers/alert-hub-state"
```

If you'd rather use a connection string (e.g. for local dev), set the
`connection_string_env` field in `config.yaml` to the env var name and
configure that env var on the Function App.

## 3. Lay out the function code

```
my-azure-alerts/
├── host.json
├── requirements.txt        # cloud-alert-hub[azure] @ git+…
├── EventGridTrigger/
│   ├── function.json       # Event Grid trigger binding
│   └── __init__.py         # 10-line wrapper that calls handle_azure_eventgrid
└── config.yaml             # see below
```

`__init__.py`:

```python
from __future__ import annotations
import logging
from cloud_alert_hub import handle_azure_eventgrid

LOG = logging.getLogger(__name__)

def main(event):
    payload = event.get_json()
    result = handle_azure_eventgrid(payload, config="./config.yaml")
    LOG.info("cloud_alert_hub: %s route=%s event_id=%s",
             result.get("status"), result.get("route_key"), result.get("event_id"))
    return result
```

`requirements.txt`:

```
cloud-alert-hub[azure] @ git+https://github.com/Tarunrj99/cloud-alert-hub.git@v0.3.4
azure-functions
```

`config.yaml`:

```yaml
app:
  name: cloud-alert-hub-azure
  environment: nonprod
  cloud: azure
  alerting_enabled: true

features:
  budget_alerts:
    enabled: true
    thresholds_percent: [50, 70, 90, 100, 125, 150, 200]
    dedupe_window_seconds: 2764800       # 32 days
    route: finops

notifications:
  slack:
    enabled: true
    webhook_url_env: SLACK_WEBHOOK_URL
    default_channel: "#azure-alerts"

routing:
  default_route: finops
  routes:
    finops:
      slack_channel: "#azure-billing-alerts"

state:
  backend: azure_blob
  account_name: REPLACE_WITH_$STG
  container: alert-hub-state
  blob_name: dedup-state.json
  # connection_string_env: AZURE_STORAGE_CONNECTION_STRING   # optional;
  # else managed identity is used
```

## 4. Deploy

```bash
# from inside my-azure-alerts/
func azure functionapp publish "$FUNCAPP" --python

# Set the Slack webhook on the function app (treat as a secret)
az functionapp config appsettings set \
  --name "$FUNCAPP" --resource-group "$RG" \
  --settings SLACK_WEBHOOK_URL='https://hooks.slack.com/services/XXX/YYY/ZZZ'
```

## 5. Wire real producers

| Source | How |
| ------ | --- |
| **Cost Management budgets** | Create an action group → Event Grid → your Function's Event Grid trigger |
| **Defender for Cloud / Sentinel alerts** | Continuous export → Event Grid topic → Function trigger |
| **Activity Log alerts** | Action group → Event Grid → Function trigger |

The Azure Event Grid adapter shipped in `cloud_alert_hub.adapters.azure_eventgrid`
normalises any of the above into the canonical alert.

## Troubleshooting

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| `ImportError: AzureBlobState requires the optional 'azure' extra` | `requirements.txt` doesn't pin `cloud-alert-hub[azure]` | Add the `[azure]` extra and redeploy |
| `403 AuthorizationPermissionMismatch` writing dedup state | Function MI missing `Storage Blob Data Contributor` on the container | Re-run the `az role assignment create` from step 2 |
| `ResourceNotFoundError` for the container | Container name in `config.yaml` doesn't match what was created | `az storage container list --account-name $STG` |
| Duplicate Slack messages for the same threshold | Budgets / Cost Management re-emits; cold starts wipe in-memory state | Set `state.backend: azure_blob` (default in this guide) and verify the principal can write |

## Next steps

- Add Sentinel / Defender alerts as additional features → [`FEATURES.md`](FEATURES.md).
- Tune what shows up in Slack → [`CONFIGURATION.md`](CONFIGURATION.md).
- Cross-cloud deploy on GCP / AWS in parallel → [`DEPLOY_GCP.md`](DEPLOY_GCP.md), [`DEPLOY_AWS.md`](DEPLOY_AWS.md).
