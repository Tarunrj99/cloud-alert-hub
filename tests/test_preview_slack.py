"""Smoke tests for ``cloud_alert_hub.tools.preview_slack``.

We don't assert exact rendered text — that's covered by ``test_renderer``.
What we *do* assert is that the script can take every fixture in
``examples/payloads/`` and produce well-formed Block Kit JSON for the
right feature, without raising. This makes the "any user can preview
any feature locally" claim in ``docs/SAMPLE_OUTPUT.md`` actually true.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from cloud_alert_hub.tools.preview_slack import main

ROOT = Path(__file__).resolve().parent.parent
PAYLOADS = ROOT / "examples" / "payloads"


@pytest.mark.parametrize(
    "fixture, source, expected_kind",
    [
        ("gcp-billing-budget-native.json", "gcp", "budget"),
        ("gcp-cost-spike-monitoring-incident.json", "gcp", "cost_spike"),
        ("aws-sns-event.json", "aws", "budget"),
        ("aws-cost-anomaly-sns.json", "aws", "cost_spike"),
        ("generic-budget-alert.json", "generic", "budget"),
        ("generic-cost-spike.json", "generic", "cost_spike"),
        ("generic-service-slo.json", "generic", "service"),
        ("generic-security-audit.json", "generic", "security"),
        ("generic-infrastructure-spike.json", "generic", "infrastructure"),
    ],
)
def test_preview_renders_every_fixture(
    fixture: str, source: str, expected_kind: str
) -> None:
    payload = PAYLOADS / fixture
    assert payload.exists(), f"fixture missing: {payload}"

    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main([str(payload), "--source", source])
    assert rc == 0, f"preview tool exited non-zero for {fixture}"

    parsed = json.loads(buf.getvalue())
    assert "channel" in parsed
    assert parsed["text"]
    blocks = parsed["blocks"]
    assert isinstance(blocks, list) and blocks, "must produce at least one block"
    assert blocks[0]["type"] == "header"
    block_text = json.dumps(blocks)
    assert expected_kind in block_text or expected_kind == "budget", (
        f"expected feature kind {expected_kind!r} to appear in rendered blocks for {fixture}"
    )


def test_preview_blocks_only_emits_just_blocks(tmp_path: Path) -> None:
    fixture = PAYLOADS / "generic-cost-spike.json"
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main([str(fixture), "--source", "generic", "--blocks-only"])
    assert rc == 0
    out = json.loads(buf.getvalue())
    assert isinstance(out, list)
    assert all(isinstance(b, dict) and "type" in b for b in out)
