"""Documentation completeness guard.

The public repository is the front door for end-users. If the architecture
diagram, the per-cloud deploy recipes, the feature list, or any of the
canonical example payloads silently disappear, the README's cross-links
break and the project looks half-finished — but unit tests would still
pass.

This file pins the docs surface area: every artefact a reader is
expected to land on must continue to exist *and* be linked from the
README. Renaming or moving a file is fine — just update both this list
and the README in the same change.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Top-level: project-meta files. These are what GitHub renders on the
# repo home page (LICENSE link, CONTRIBUTING button, etc.).
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL = [
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "config.example.yaml",
    "pyproject.toml",
    "Makefile",
]


@pytest.mark.parametrize("name", REQUIRED_TOP_LEVEL)
def test_top_level_meta_file_exists(name: str) -> None:
    path = REPO_ROOT / name
    assert path.is_file(), f"missing top-level file: {name}"
    assert path.stat().st_size > 0, f"empty top-level file: {name}"


# ---------------------------------------------------------------------------
# docs/ — the user manual. Every doc must exist and the README must
# link to it (so a reader landing on README finds it).
# ---------------------------------------------------------------------------

REQUIRED_DOCS = [
    "QUICKSTART.md",
    "CONFIGURATION.md",
    "ARCHITECTURE.md",
    "FEATURES.md",
    "RECIPES.md",
    "SAMPLE_OUTPUT.md",
    "SCENARIOS.md",
    "DEBUG_RUNBOOK.md",
    "DEPLOY_GCP.md",
    "DEPLOY_AWS.md",
    "DEPLOY_AZURE.md",
]


@pytest.mark.parametrize("name", REQUIRED_DOCS)
def test_required_doc_exists(name: str) -> None:
    path = REPO_ROOT / "docs" / name
    assert path.is_file(), f"missing docs/{name}"
    assert path.stat().st_size > 200, (
        f"docs/{name} is suspiciously short ({path.stat().st_size} bytes); "
        "did someone empty it?"
    )


# Subset of the docs that absolutely must be cross-linked from the
# README so a casual visitor finds them. Not every doc has to be in
# the README hero — but these are the high-value ones.
README_MUST_LINK = [
    "docs/QUICKSTART.md",
    "docs/CONFIGURATION.md",
    "docs/ARCHITECTURE.md",
    "docs/FEATURES.md",
    "docs/RECIPES.md",
    "docs/SAMPLE_OUTPUT.md",
    "docs/DEBUG_RUNBOOK.md",
    "docs/DEPLOY_GCP.md",
    "docs/DEPLOY_AWS.md",
    "docs/DEPLOY_AZURE.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "LICENSE",
]


def test_readme_links_to_all_high_value_docs() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    missing = [target for target in README_MUST_LINK if target not in readme]
    assert not missing, (
        "README.md does not reference these high-value docs: "
        f"{missing}. Add them to the docs nav so first-time readers "
        "can find them."
    )


# ---------------------------------------------------------------------------
# Examples — every cloud has a runnable scaffold and every feature has
# a fixture that reproduces its Slack output offline.
# ---------------------------------------------------------------------------

REQUIRED_EXAMPLE_DIRS = [
    "examples/gcp-cloud-function",
    "examples/aws-lambda",
    "examples/local-dev",
]


@pytest.mark.parametrize("rel", REQUIRED_EXAMPLE_DIRS)
def test_example_directory_is_runnable_scaffold(rel: str) -> None:
    """Each example directory must contain at minimum a README + an
    entry-point file + a requirements.txt (or equivalent) so a reader
    can copy-paste and deploy."""
    base = REPO_ROOT / rel
    assert base.is_dir(), f"missing example directory: {rel}"
    files = {p.name for p in base.iterdir() if p.is_file()}
    must_contain_one_of_each: dict[str, set[str]] = {
        "readme":       {"README.md", "readme.md"},
        "requirements": {"requirements.txt", "pyproject.toml"},
    }
    for label, candidates in must_contain_one_of_each.items():
        assert files & candidates, (
            f"example {rel} is missing a {label} file (one of {sorted(candidates)}); "
            f"actual files = {sorted(files)}"
        )


REQUIRED_PAYLOAD_FIXTURES = [
    # one (cloud × feature) per row — these back every screenshot in
    # docs/SAMPLE_OUTPUT.md, so dropping one breaks the docs.
    "gcp-billing-budget-native.json",
    "gcp-cost-spike-monitoring-incident.json",
    "gcp-pubsub-envelope.json",
    "aws-sns-event.json",
    "aws-cost-anomaly-sns.json",
    "generic-budget-alert.json",
    "generic-cost-spike.json",
    "generic-service-slo.json",
    "generic-security-audit.json",
    "generic-infrastructure-spike.json",
]


@pytest.mark.parametrize("name", REQUIRED_PAYLOAD_FIXTURES)
def test_example_payload_fixture_exists(name: str) -> None:
    path = REPO_ROOT / "examples" / "payloads" / name
    assert path.is_file(), (
        f"examples/payloads/{name} is missing — docs/SAMPLE_OUTPUT.md "
        "references it as a reproducible fixture."
    )
    assert path.read_text(encoding="utf-8").strip().startswith(("{", "[")), (
        f"examples/payloads/{name} is not valid JSON (must start with {{ or [)"
    )


# ---------------------------------------------------------------------------
# Architecture doc must mention all the moving parts so a reader
# understands the full pipeline.
# ---------------------------------------------------------------------------

ARCH_KEY_TOPICS = [
    "adapter",        # cloud-specific ingestion
    "policy",         # feature matching + dedupe
    "feature",        # plug-in features
    "manifest",       # runtime / version compatibility check (= killswitch)
    "renderer",       # Slack/email rendering
    "state",          # dedupe state backend (memory / file / GCS / S3 / Azure)
    "notifier",       # actual Slack / email delivery
    "config",         # config layering
]


def test_architecture_doc_covers_every_component() -> None:
    arch = (REPO_ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8").lower()
    missing = [topic for topic in ARCH_KEY_TOPICS if topic not in arch]
    assert not missing, (
        "docs/ARCHITECTURE.md is missing the following moving parts of the "
        f"pipeline: {missing}. Document every component so readers can map "
        "code paths to the architecture diagram."
    )


# ---------------------------------------------------------------------------
# Each feature shipped under src/cloud_alert_hub/features/ must be
# named in docs/FEATURES.md. Otherwise users can't discover it.
# ---------------------------------------------------------------------------

def _shipped_feature_names() -> list[str]:
    feature_dir = REPO_ROOT / "src" / "cloud_alert_hub" / "features"
    return sorted(
        p.stem for p in feature_dir.glob("*.py")
        if p.is_file() and p.stem not in {"__init__", "base"}
    )


def test_every_shipped_feature_is_documented() -> None:
    features = _shipped_feature_names()
    assert features, "no features discovered under src/cloud_alert_hub/features/"
    docs = (REPO_ROOT / "docs" / "FEATURES.md").read_text(encoding="utf-8")
    missing = [name for name in features if name not in docs]
    assert not missing, (
        f"docs/FEATURES.md does not mention these shipped features: {missing}. "
        "Every feature in src/cloud_alert_hub/features/ must have a section "
        "describing its kind / claims rule / config knobs."
    )
