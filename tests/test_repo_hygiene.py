"""Public-repo hygiene scanner.

This file is the long-term safety net for the rule: **the public GitHub
repository must never contain real production identifiers**. It scans
every tracked source / config / docs file for a list of forbidden
patterns and fails the test suite if any reappears.

What "real" means here:

* GCP project IDs of the reference deployment (``glossy-fastness-305315``
  etc.).
* Real billing-account IDs (anything matching the GCP
  ``01XXXX-XXXXXX-XXXXXX`` shape with non-placeholder content).
* Real Slack webhook URLs (``hooks.slack.com/services/T...``).
* Real recipient email addresses (the three ops on-call addresses).
* The reference deployment's company name.
* Bucket / topic names tied to the reference deployment.

Things deliberately **not** forbidden because they're part of the
public identity of the project:

* The author / repo owner GitHub handle (``Tarunrj99``).
* The author's name as it appears in ``LICENSE`` / ``pyproject.toml``.
* Generic placeholders such as ``my-project``, ``01XXXX-YYYYYY-ZZZZZZ``,
  ``example.com``.

If you ever need to mention something genuinely private in the public
repo (e.g. for an example log line), replace it with a placeholder. If
this test is failing, *don't* add the leaking string to the allowlist —
remove the string from the file instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# What to scan: every file under the repo, except…
# ---------------------------------------------------------------------------

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "build",
    "dist",
    ".mypy_cache",
    # ``pip install -e .`` regenerates this; it mirrors source content
    # by definition, so scanning it is double-counting.
    "cloud_alert_hub.egg-info",
}

_SKIP_FILE_SUFFIXES = {
    # Binary / non-text formats that aren't shipped to PyPI / GitHub
    # users as readable code anyway. Keeps the scan fast.
    ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico", ".svg",
    ".zip", ".gz", ".tar", ".whl", ".so", ".dylib",
}


def _iter_repo_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in _SKIP_FILE_SUFFIXES:
            continue
        # The hygiene test itself contains the forbidden patterns
        # by definition — skip it explicitly.
        if path.resolve() == Path(__file__).resolve():
            continue
        files.append(path)
    return files


# ---------------------------------------------------------------------------
# What to forbid. Keep these *patterns* tight so they don't flag
# legitimate placeholders. Each entry is (compiled_regex, human_reason).
# ---------------------------------------------------------------------------

_FORBIDDEN: list[tuple[re.Pattern[str], str]] = [
    # The reference deployment's GCP project IDs.
    (
        re.compile(r"glossy-fastness-305315", re.IGNORECASE),
        "real GCP project id from the reference deployment",
    ),
    # Variants of the reference org's project naming convention.
    (
        re.compile(r"\bsatschel[-_ ]?(?:nonprod|prod|beta|dev|staging|qa)\b", re.IGNORECASE),
        "reference deployment project / environment name",
    ),
    # The reference org's bare company name, in any case.
    (
        re.compile(r"\bsatschel\b", re.IGNORECASE),
        "reference deployment company name",
    ),
    # A real Slack incoming webhook URL. We allow the bare host (used in
    # docs) but not a webhook *path* (the second path segment is the
    # team-id and is a secret).
    (
        re.compile(r"hooks\.slack\.com/services/T[A-Z0-9]{6,}/B[A-Z0-9]{6,}/[A-Za-z0-9]{16,}"),
        "real Slack incoming-webhook URL (contains team / channel / secret tokens)",
    ),
    # Real GCP billing-account IDs. Placeholders use ``XXXX``/``YYYY``/``ZZZZ``
    # or hex-only patterns; this regex flags the realistic alphanumeric mix.
    (
        re.compile(
            r"\b01"
            r"(?!XXXX-YYYYYY-ZZZZZZ)"  # the placeholder used in tests / fixtures
            r"(?!ABCD-EFGH-IJKL)"      # the placeholder used in test_public_api
            r"[A-Z0-9]{4}-[A-Z0-9]{6}-[A-Z0-9]{6}\b"
        ),
        "real-looking GCP billing-account id (use placeholder 01XXXX-YYYYYY-ZZZZZZ)",
    ),
    # The three production on-call email addresses, by username or domain.
    (
        re.compile(r"\bjayant\.sonsurkar\b", re.IGNORECASE),
        "real recipient email username (jayant.sonsurkar)",
    ),
    (
        re.compile(r"\btarun\.saini@", re.IGNORECASE),
        "real recipient email address (tarun.saini@…)",
    ),
    (
        re.compile(r"\bshubham\.nagarwal\b", re.IGNORECASE),
        "real recipient email username (shubham.nagarwal)",
    ),
    (
        re.compile(r"@satschel\.com", re.IGNORECASE),
        "reference deployment email domain (@satschel.com)",
    ),
    # Real bucket / topic names from the reference deployment.
    (
        re.compile(r"\bbilling-alerts-nonprod\b", re.IGNORECASE),
        "reference deployment Pub/Sub topic name",
    ),
    (
        re.compile(r"\b[a-z0-9-]+-alert-hub-state\b"),
        "reference deployment GCS dedup bucket name",
    ),
    # Internal Slack channel naming, e.g. #GCP-Alerts-Nonprod.
    (
        re.compile(r"#GCP-Alerts-(?:Nonprod|Prod|Beta)", re.IGNORECASE),
        "reference deployment Slack channel name",
    ),
]


# ---------------------------------------------------------------------------
# Per-pattern allowlist — keys whose presence is *intentional* in the
# public repo (e.g. a docs example or a wildcard in this very file).
# We keep the surface minimal: each entry is a (path-suffix, pattern-reason)
# tuple. Anything else triggers a failure.
# ---------------------------------------------------------------------------

_ALLOWED_FILE_REASON: set[tuple[str, str]] = {
    # The bucket-name regex is broad enough to match a generic example
    # bucket name in the docs (e.g. ``my-org-alert-hub-state``). We
    # keep doc references for now but flag any *new* matches by
    # explicit allowlist entries.
}


def _is_allowlisted(path: Path, reason: str, line: str) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    if (rel, reason) in _ALLOWED_FILE_REASON:
        return True
    # Generic bucket pattern: tolerate strings of the form
    # ``<owner>-alert-hub-state`` if they look like a placeholder
    # (contain one of the placeholder words).
    if "GCS dedup bucket name" in reason:
        if any(token in line.lower() for token in ("my-", "your-", "<", "example", "demo", "placeholder")):
            return True
    return False


@pytest.mark.parametrize("path", _iter_repo_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_no_real_information_leaks_in_public_repo(path: Path) -> None:
    """Every tracked file must be free of the forbidden patterns above.

    Run with ``pytest tests/test_repo_hygiene.py -k 'README'`` to scope
    to a specific file when iterating.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Binary file we couldn't pre-filter — skip rather than fail.
        pytest.skip(f"non-utf8 file: {path}")
    failures: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for pattern, reason in _FORBIDDEN:
            match = pattern.search(line)
            if not match:
                continue
            if _is_allowlisted(path, reason, line):
                continue
            failures.append(
                f"{path.relative_to(REPO_ROOT)}:{line_no}: matched {reason!r} "
                f"({match.group(0)!r}). Replace with a placeholder."
            )
    assert not failures, (
        "Real-information leak detected in the public repo. The whole point "
        "of this test is to keep the public repository scrubbed of any "
        "production identifier. Replace the offending value(s) with "
        "documented placeholders ('my-project', '01XXXX-YYYYYY-ZZZZZZ', "
        "'finance@example.com', etc.) — do NOT add the value to the "
        "allowlist.\n\nFailures:\n  " + "\n  ".join(failures)
    )


def test_hygiene_scanner_actually_scans_some_files() -> None:
    """Sanity check: if a refactor accidentally narrows _SKIP_DIRS too
    aggressively or moves the repo root, the parametrised test above
    would silently pass with zero files. Lock the floor at 30 files
    (the repo currently has 80+).
    """
    files = _iter_repo_files()
    assert len(files) >= 30, (
        f"Hygiene scanner only found {len(files)} files to scan — looks "
        "like the file walk is broken; please re-check _SKIP_DIRS / repo "
        "layout."
    )


def test_hygiene_scanner_actually_catches_known_leaks(tmp_path: Path) -> None:
    """Self-test: feed the forbidden patterns into the scanner and
    confirm every one of them is detected.

    Without this, the scanner could be silently disabled (e.g. someone
    rewrites a regex incorrectly or empties ``_FORBIDDEN``) and the
    parametrised test above would still pass on a clean repo. This
    test never reads the real repo — it constructs synthetic files.
    """
    samples = {
        "fake_a.txt": "PROJECT_ID=glossy-fastness-305315  # leaked project id",
        "fake_b.txt": "team: Satschel Engineering  # leaked company",
        "fake_b2.txt": "project=satschel-nonprod env=satschel-prod",
        "fake_c.txt": "topic = projects/x/topics/billing-alerts-nonprod",
        "fake_d.txt": "email: jayant.sonsurkar@example.com",
        "fake_e.txt": "addr: tarun.saini@somecompany.com",
        "fake_f.txt": "user: shubham.nagarwal@somewhere",
        "fake_g.txt": "domain @satschel.com",
        "fake_h.txt": "bucket: my-org-prod-alert-hub-state",  # not allowlisted
        "fake_i.txt": (
            "url=https://hooks.slack.com/services/T0123ABC/B0456DEF/abcd1234efgh5678ijklmnopqrstuvwx"
        ),
        "fake_j.txt": "billing_account: 01ABCD-EFGH12-IJKL34",  # real-looking, not the placeholder
        "fake_k.txt": "channel: #GCP-Alerts-Nonprod",
    }
    for name, content in samples.items():
        (tmp_path / name).write_text(content, encoding="utf-8")

    detected_reasons: set[str] = set()
    for path in tmp_path.iterdir():
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            for pattern, reason in _FORBIDDEN:
                if pattern.search(line):
                    detected_reasons.add(reason)

    expected_reasons = {reason for _, reason in _FORBIDDEN}
    missing = expected_reasons - detected_reasons
    assert not missing, (
        "Hygiene scanner self-test failed — these forbidden patterns "
        f"were NOT detected on synthetic samples: {missing}. Either the "
        "regex is broken or the sample list is incomplete."
    )
