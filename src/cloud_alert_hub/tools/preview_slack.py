"""Render a Slack message for any payload, locally, without sending anything.

This is the canonical way to *see* what an alert would look like. It runs the
exact same pipeline as production (adapter → enrichment → feature match →
renderer) but stops just before the notifier so nothing leaves your laptop.

Examples::

    # Preview a GCP Pub/Sub envelope (e.g. a real billing-budget message):
    python -m cloud_alert_hub.tools.preview_slack \\
        --source gcp examples/payloads/gcp-billing-budget-native.json

    # Preview a canonical generic payload (cost_spike):
    python -m cloud_alert_hub.tools.preview_slack \\
        --source generic examples/payloads/generic-cost-spike.json

    # With your own deployment config (overrides bundled defaults):
    python -m cloud_alert_hub.tools.preview_slack \\
        --source gcp --config deploy/nonprod/config.yaml payload.json

    # Print only the Block Kit blocks (e.g. to paste into Slack's Block Kit
    # Builder at https://api.slack.com/tools/block-kit-builder):
    python -m cloud_alert_hub.tools.preview_slack \\
        --source generic --blocks-only examples/payloads/generic-service-slo.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ..adapters import (
    from_aws_sns,
    from_azure_eventgrid,
    from_gcp_pubsub,
    from_generic,
)
from ..api import _enrich_from_config
from ..config import load_config
from ..features import load_enabled_features
from ..renderer import render_slack

_SOURCE_ADAPTERS = {
    "gcp": from_gcp_pubsub,
    "aws": from_aws_sns,
    "azure": from_azure_eventgrid,
    "generic": from_generic,
}


def _read_payload(path: str) -> Any:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Payload at {path!r} is not valid JSON: {exc}") from exc


def _force_enable_all_features(cfg) -> None:
    """Make every feature claim eligible during preview.

    We don't *enable* features in the operational sense (no notifiers run);
    we just need their ``match()`` logic to be available so the renderer can
    show severity and feature-specific blocks.
    """
    for name in (
        "budget_alerts",
        "cost_spike",
        "service_slo",
        "security_audit",
        "infrastructure_spike",
    ):
        section = cfg.feature(name)
        section["enabled"] = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cloud_alert_hub.tools.preview_slack",
        description="Render a Slack message for a payload, locally, without sending it.",
    )
    parser.add_argument(
        "payload",
        help="Path to a JSON file containing the raw event (Pub/Sub envelope, "
        "SNS record, Event Grid batch, or canonical alert dict).",
    )
    parser.add_argument(
        "--source",
        choices=sorted(_SOURCE_ADAPTERS.keys()),
        default="generic",
        help="Which adapter to use (default: generic).",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to a YAML config file (overrides bundled defaults).",
    )
    parser.add_argument(
        "--channel",
        default="#alerts-finops",
        help="Slack channel string included in the rendered message (cosmetic only).",
    )
    parser.add_argument(
        "--blocks-only",
        action="store_true",
        help="Print only the Block Kit `blocks` array (paste into Slack Block Kit Builder).",
    )
    args = parser.parse_args(argv)

    payload = _read_payload(args.payload)
    cfg = load_config(args.config)
    _force_enable_all_features(cfg)

    adapter = _SOURCE_ADAPTERS[args.source]
    alert = adapter(payload)
    alert = _enrich_from_config(alert, cfg)

    for feature in load_enabled_features(cfg):
        if feature.claims(alert):
            match = feature.match(alert)
            alert.severity = match.severity or alert.severity or "info"
            alert.route_key = match.route_key or alert.route_key
            alert.labels.update(match.labels or {})
            break

    display = cfg.get("notifications", "slack", "display", default={}) or {}
    msg = render_slack(alert, channel=args.channel, display=display)

    if args.blocks_only:
        print(json.dumps(msg.blocks, indent=2))
    else:
        out = {"channel": msg.channel, "text": msg.text, "blocks": msg.blocks}
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
