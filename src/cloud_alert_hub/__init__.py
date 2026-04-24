"""cloud_alert_hub — A cloud-agnostic alerting hub.

A single installable package that ingests billing, SLO, security, and
infrastructure events from any cloud (GCP Pub/Sub, AWS SNS, Azure Event Grid,
or a generic HTTP payload), runs them through a policy engine, and delivers
them to Slack / email according to a single user-supplied YAML config.

Typical usage from a GCP Cloud Function:

    from cloud_alert_hub import handle_gcp_pubsub

    def alert_handler(event, context):
        return handle_gcp_pubsub(event, config="./config.yaml")

See the project README and ``examples/`` for deployment-ready starters.
"""

from .api import (
    handle_aws_sns,
    handle_azure_eventgrid,
    handle_gcp_pubsub,
    process_alert,
    run,
)
from .config import Config, load_config
from .models import CanonicalAlert, DeliveryTarget, PolicyDecision

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "run",
    "process_alert",
    "handle_gcp_pubsub",
    "handle_aws_sns",
    "handle_azure_eventgrid",
    "load_config",
    "Config",
    "CanonicalAlert",
    "DeliveryTarget",
    "PolicyDecision",
]
