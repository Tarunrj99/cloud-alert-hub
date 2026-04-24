"""End-to-end alert processor: policy → render → deliver → retry → dead-letter."""

from __future__ import annotations

import time
from typing import Any, Callable

from .config import Config
from .deadletter import write_dead_letter
from .models import CanonicalAlert
from .notifiers.email import send_email
from .notifiers.slack import send_slack
from .policy import evaluate_policy
from .renderer import render_email, render_slack
from .state import BaseState
from .telemetry import MetricsTracker


class AlertProcessor:
    def __init__(self, config: Config, state: BaseState, metrics: MetricsTracker) -> None:
        self.config = config
        self.state = state
        self.metrics = metrics

    def process(self, alert: CanonicalAlert) -> dict[str, Any]:
        self.metrics.inc("events_received_total")
        decision = evaluate_policy(alert, self.config, self.state)

        if not decision.should_deliver:
            self.metrics.inc("events_suppressed_total")
            response: dict[str, Any] = {
                "status": "suppressed",
                "reason": decision.suppressed_reason,
                "event_id": alert.event_id,
                "route_key": decision.route_key,
                "tags": decision.delivery_tags,
            }
            if self.config.debug_mode:
                response["debug"] = {"trace": decision.trace, "alert": alert.model_dump(mode="json")}
            return response

        self.metrics.inc("events_processed_total")
        results: dict[str, Any] = {
            "status": "processed",
            "event_id": alert.event_id,
            "route_key": decision.route_key,
            "deliveries": {},
        }
        delivery_errors: list[dict[str, str]] = []

        if decision.target.slack_enabled:
            slack_msg = render_slack(alert, decision.target.slack_channel)
            results["deliveries"]["slack"] = self._deliver_with_retry(
                channel="slack",
                event_id=alert.event_id,
                send_call=lambda: send_slack(
                    slack_msg,
                    webhook_env_var=self.config.slack_webhook_env,
                    timeout_seconds=int(self.config.delivery.get("timeout_seconds", 8)),
                    dry_run=self.config.dry_run,
                ),
            )
            if results["deliveries"]["slack"].get("status") in {"failed", "error"}:
                delivery_errors.append({"channel": "slack", "status": results["deliveries"]["slack"]["status"]})

        if decision.target.email_enabled and decision.target.email_recipients:
            email_msg = render_email(alert, decision.target.email_recipients, self.config.email_from_address)
            results["deliveries"]["email"] = self._deliver_with_retry(
                channel="email",
                event_id=alert.event_id,
                send_call=lambda: send_email(
                    email_msg,
                    provider=self.config.email_provider,
                    dry_run=self.config.dry_run,
                ),
            )
            if results["deliveries"]["email"].get("status") in {"failed", "error"}:
                delivery_errors.append({"channel": "email", "status": results["deliveries"]["email"]["status"]})

        if delivery_errors:
            self.metrics.inc("deliveries_failed_total")
            dead_letter_path = write_dead_letter(
                {
                    "event_id": alert.event_id,
                    "route_key": decision.route_key,
                    "errors": delivery_errors,
                    "alert": alert.model_dump(mode="json"),
                }
            )
            results["dead_letter"] = {"status": "written", "path": dead_letter_path}
        else:
            self.metrics.inc("deliveries_success_total")

        if self.config.debug_mode:
            results["debug"] = {"trace": decision.trace, "alert": alert.model_dump(mode="json")}
        return results

    def _deliver_with_retry(self, channel: str, event_id: str, send_call: Callable[[], dict]) -> dict[str, Any]:
        delivery_cfg = self.config.delivery
        max_retries = int(delivery_cfg.get("max_retries", 3))
        backoff = list(delivery_cfg.get("retry_backoff_seconds", [2, 5, 10]))
        attempts = max_retries + 1
        last_result: dict[str, Any] = {"status": "failed"}

        for attempt in range(attempts):
            self.metrics.inc(f"{channel}_attempt_total")
            try:
                last_result = send_call()
            except Exception as exc:  # noqa: BLE001 — surface any SDK error as a retryable failure
                last_result = {"status": "error", "error": str(exc)}

            if last_result.get("status") in {"sent", "queued", "dry_run", "skipped"}:
                self.metrics.inc(f"{channel}_success_total")
                return {**last_result, "attempt": attempt + 1}

            if attempt < max_retries:
                sleep_for = backoff[min(attempt, len(backoff) - 1)] if backoff else 1
                time.sleep(float(sleep_for))

        self.metrics.inc(f"{channel}_failed_total")
        return {**last_result, "attempt": attempts, "event_id": event_id}
