"""GCP Cloud Function entrypoint (2nd gen, Pub/Sub / CloudEvent trigger).

This file is the whole contents of your function. The heavy lifting lives in
the ``cloud_alert_hub`` library, which is installed from GitHub via
``requirements.txt``. All you do here is wire the cloud event into the
library's public API.
"""

from __future__ import annotations

import os

import functions_framework

from cloud_alert_hub import handle_gcp_pubsub

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


@functions_framework.cloud_event
def alert_handler(cloud_event):
    """Triggered by Pub/Sub. ``cloud_event.data`` carries the Pub/Sub envelope."""
    result = handle_gcp_pubsub(cloud_event.data, config=CONFIG_PATH)
    print(f"cloud_alert_hub: {result.get('status')} route={result.get('route_key')} event_id={result.get('event_id')}")
    return result
