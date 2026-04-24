"""AWS Lambda entrypoint (SNS trigger).

The packaged layer (or bundled ``requirements.txt``) provides ``cloud_alert_hub``;
everything else is already in this file.
"""

from __future__ import annotations

import json
import os

from cloud_alert_hub import handle_aws_sns

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def lambda_handler(event, context):  # noqa: ANN001 — AWS Lambda signature
    result = handle_aws_sns(event, config=CONFIG_PATH)
    print(json.dumps({"cloud_alert_hub": result}, default=str))
    return result
